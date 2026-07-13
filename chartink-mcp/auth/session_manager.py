"""Chartink session management with Playwright login and cookie persistence.

Browser login runs in a **subprocess** (``auth/browser_login_worker.py``) so sync
Playwright never runs inside FastAPI's asyncio loop. Set ``CHARTINK_EMAIL`` and
``CHARTINK_PASSWORD`` on Render for fully automated login and refresh.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from loguru import logger
from app.config import PROJECT_ROOT, get_settings
from storage.repository import ChartinkRepository


class AuthenticationError(Exception):
    """Raised when Chartink authentication fails."""


NOT_AUTHENTICATED_MESSAGE = (
    "Chartink session is not authenticated. Set CHARTINK_EMAIL and CHARTINK_PASSWORD "
    "on the server (CHARTINK_AUTO_LOGIN=true) and POST /refresh-session."
)


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
            cookies = self._browser_login_subprocess(email, password)
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

    def ensure_authenticated(self) -> None:
        """Validate session; optionally run automated browser login when configured."""
        self.load_cookies()
        if self.validate_session():
            return
        if self._can_auto_login():
            logger.info("Session invalid — attempting automated Chartink login")
            try:
                self.auto_reauthenticate()
                if self.validate_session():
                    logger.info("Automated Chartink login succeeded")
                    return
            except AuthenticationError as exc:
                logger.warning("Automated login failed: {}", exc)
        raise AuthenticationError(NOT_AUTHENTICATED_MESSAGE)

    def _can_auto_login(self) -> bool:
        return bool(
            self.settings.chartink_auto_login
            and self.settings.chartink_email
            and self.settings.chartink_password
        )

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

    def try_startup_login(self) -> bool:
        """Attempt login on startup when configured. Returns True if session is valid."""
        if not self.settings.chartink_startup_auto_login:
            logger.info("Startup auto-login disabled (CHARTINK_STARTUP_AUTO_LOGIN=false)")
            return self.validate_session()
        if not self._can_auto_login():
            logger.warning(
                "CHARTINK_EMAIL/PASSWORD not set — set them for automated login"
            )
            return self.validate_session()
        if self.validate_session():
            logger.info("Existing Chartink session is valid")
            return True
        logger.info("No valid session — running startup automated login")
        try:
            self.auto_reauthenticate()
            return self.validate_session()
        except Exception as exc:
            logger.warning("Startup automated login failed (non-fatal): {}", exc)
            return False

    def get_cookies(self) -> dict[str, str]:
        """Return current cookies, loading from disk if needed."""
        with self._lock:
            if not self._cookies:
                self.load_cookies()
            return dict(self._cookies)

    def merge_cookies(self, cookies: dict[str, str]) -> None:
        """Merge cookies (e.g. rotated XSRF after a page GET) into the live session."""
        if not cookies:
            return
        with self._lock:
            self._cookies.update({k: str(v) for k, v in cookies.items() if v is not None})

    def sync_cookies_from_client(self, client: httpx.Client) -> None:
        """Pull the httpx cookie jar back into session state after a request."""
        # Prefer the last value when the jar contains duplicates (common for XSRF).
        jar_cookies: dict[str, str] = {}
        for cookie in client.cookies.jar:
            jar_cookies[cookie.name] = cookie.value
        self.merge_cookies(jar_cookies)

    def get_http_client(self) -> httpx.Client:
        """Build an httpx client with current session cookies."""
        cookies = self.get_cookies()
        client = httpx.Client(
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
        # Bind auth cookies to chartink.com so httpx does not accumulate
        # duplicate nameless-domain entries that break Laravel CSRF checks.
        host = "chartink.com"
        for name, value in cookies.items():
            if not value:
                continue
            if name.startswith("_ga") or name.startswith("_GRECAPTCHA"):
                continue
            client.cookies.set(name, str(value), domain=host, path="/")
        return client

    def _http_get(self, url: str) -> httpx.Response:
        with self.get_http_client() as client:
            return client.get(url)

    def _browser_login_subprocess(self, email: str, password: str) -> dict[str, str]:
        """Run sync Playwright in a child process (isolated from asyncio)."""
        worker = Path(__file__).resolve().parent / "browser_login_worker.py"
        timeout_sec = int(self.settings.playwright_timeout_ms / 1000) + 60
        env = os.environ.copy()
        browsers_path = self.settings.playwright_browsers_path.resolve()
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_path)
        try:
            proc = subprocess.run(
                [sys.executable, str(worker), email, password],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                cwd=str(PROJECT_ROOT),
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AuthenticationError(
                f"Browser login timed out after {timeout_sec}s"
            ) from exc

        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip() or "unknown error"
            try:
                err_payload = json.loads(detail)
                detail = err_payload.get("error", detail)
            except json.JSONDecodeError:
                pass
            raise AuthenticationError(f"Browser login failed: {detail}")

        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise AuthenticationError("Browser login returned invalid JSON") from exc

        cookies = {k: str(v) for k, v in payload.get("cookies", {}).items()}
        self._csrf_token = payload.get("csrf_token")
        if not cookies:
            raise AuthenticationError("Browser login returned no cookies")
        return cookies
