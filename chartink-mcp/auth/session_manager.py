"""Chartink session management with Playwright login and cookie persistence."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from loguru import logger
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.config import get_settings
from storage.repository import ChartinkRepository


class AuthenticationError(Exception):
    """Raised when Chartink authentication fails."""


class SessionManager:
    """Manages Chartink browser login, cookie persistence, and session validation."""

    def __init__(self, repository: ChartinkRepository | None = None) -> None:
        self.settings = get_settings()
        self.repository = repository
        self._lock = threading.RLock()
        self._cookies: dict[str, str] = {}
        self._csrf_token: str | None = None
        self._last_login_at: datetime | None = None
        self._session_record_id: int | None = None

    @property
    def base_url(self) -> str:
        return self.settings.chartink_base_url.rstrip("/")

    def login(self, email: str | None = None, password: str | None = None) -> dict[str, str]:
        """Authenticate via browser login and persist session cookies."""
        email = email or self.settings.chartink_email
        password = password or self.settings.chartink_password
        if not email or not password:
            raise AuthenticationError(
                "CHARTINK_EMAIL and CHARTINK_PASSWORD must be set for login"
            )

        with self._lock:
            logger.info("Starting Chartink browser login for {}", email)
            cookies = self._browser_login(email, password)
            self._cookies = cookies
            self._last_login_at = datetime.now(timezone.utc)
            self.save_cookies(cookies)
            if self.repository:
                record = self.repository.save_session(
                    cookies=cookies,
                    csrf_token=self._csrf_token,
                    expires_at=self._last_login_at + timedelta(hours=12),
                )
                self._session_record_id = record.id
            logger.info("Chartink login successful, {} cookies stored", len(cookies))
            return cookies

    def logout(self) -> None:
        """Clear local session state and invalidate persisted cookies."""
        with self._lock:
            self._cookies = {}
            self._csrf_token = None
            self._last_login_at = None
            self._session_record_id = None
            cookies_path = self.settings.cookies_file
            if cookies_path.exists():
                cookies_path.unlink()
            if self.repository:
                self.repository.invalidate_sessions()
            logger.info("Chartink session cleared")

    def validate_session(self) -> bool:
        """Check whether the current session is authenticated."""
        with self._lock:
            if not self._cookies:
                self.load_cookies()
            if not self._cookies:
                return False
            try:
                response = self._http_get(f"{self.base_url}/login")
                if response.status_code != 200:
                    return False
                body = response.text.lower()
                final_path = response.url.path.lower()

                if "login-email" in body and "login-password" in body:
                    return False

                authenticated = (
                    "logout" in body
                    or "scan_dashboard" in final_path
                    or "scan_dashboard" in body
                )
                if authenticated:
                    if self.repository and self._session_record_id:
                        self.repository.mark_session_validated(self._session_record_id, True)
                    return True
                return "ci_session" in self._cookies and "login" not in final_path
            except httpx.HTTPError as exc:
                logger.warning("Session validation failed: {}", exc)
                return False

    def refresh_session(self) -> dict[str, str]:
        """Re-authenticate if the session is invalid."""
        with self._lock:
            if self.validate_session():
                logger.debug("Session still valid, skipping refresh")
                return self._cookies
            logger.info("Session expired or invalid, re-authenticating")
            return self.auto_reauthenticate()

    def save_cookies(self, cookies: dict[str, str] | None = None) -> None:
        """Persist cookies to disk and database."""
        cookies = cookies or self._cookies
        if not cookies:
            return
        path = self.settings.cookies_file
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cookies": cookies,
            "csrf_token": self._csrf_token,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.debug("Cookies saved to {}", path)

    def load_cookies(self) -> dict[str, str]:
        """Load cookies from disk into memory."""
        path = self.settings.cookies_file
        if not path.exists():
            if self.repository:
                record = self.repository.get_latest_valid_session()
                if record and record.cookies_json:
                    self._cookies = {k: str(v) for k, v in record.cookies_json.items()}
                    self._csrf_token = record.csrf_token
                    self._session_record_id = record.id
                    return self._cookies
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cookies = data.get("cookies", {})
            self._cookies = {k: str(v) for k, v in cookies.items()}
            self._csrf_token = data.get("csrf_token")
            logger.debug("Loaded {} cookies from {}", len(self._cookies), path)
            return self._cookies
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load cookies from {}: {}", path, exc)
            return {}

    def auto_reauthenticate(self) -> dict[str, str]:
        """Attempt cookie reuse, then fall back to browser login."""
        self.load_cookies()
        if self._cookies and self.validate_session():
            return self._cookies
        return self.login()

    def get_cookies(self) -> dict[str, str]:
        """Return current cookies, loading from disk if needed."""
        with self._lock:
            if not self._cookies:
                self.load_cookies()
            return dict(self._cookies)

    def get_http_client(self) -> httpx.Client:
        """Build an httpx client with current session cookies."""
        cookies = self.get_cookies()
        return httpx.Client(
            cookies=cookies,
            timeout=self.settings.request_timeout_seconds,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/json,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
        )

    def _http_get(self, url: str) -> httpx.Response:
        with self.get_http_client() as client:
            return client.get(url)

    def _browser_login(self, email: str, password: str) -> dict[str, str]:
        cookies: dict[str, str] = {}
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=self.settings.playwright_headless
                )
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    )
                )
                page = context.new_page()
                page.set_default_timeout(self.settings.playwright_timeout_ms)
                page.goto(f"{self.base_url}/login", wait_until="domcontentloaded")

                page.fill("#login-email", email)
                page.fill("#login-password", password)

                login_btn = page.get_by_role("button", name="Log in")
                if login_btn.count() > 0:
                    login_btn.click()
                else:
                    page.locator("#login-password").press("Enter")

                try:
                    page.wait_for_url(
                        lambda url: "/login" not in url,
                        timeout=self.settings.playwright_timeout_ms,
                    )
                except PlaywrightTimeoutError:
                    if "/login" in page.url:
                        raise AuthenticationError(
                            "Login did not complete. Chartink uses reCAPTCHA — "
                            "set PLAYWRIGHT_HEADLESS=false in .env and run login_test "
                            "again to solve it in the browser window."
                        ) from None

                for cookie in context.cookies():
                    cookies[cookie["name"]] = cookie["value"]

                try:
                    csrf_meta = page.locator("meta[name='csrf-token']").first
                    if csrf_meta.count():
                        self._csrf_token = csrf_meta.get_attribute("content")
                except Exception:
                    pass

                browser.close()
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError(f"Browser login failed: {exc}") from exc

        if "ci_session" not in cookies:
            logger.warning("ci_session cookie not found; session may be incomplete")
        return cookies
