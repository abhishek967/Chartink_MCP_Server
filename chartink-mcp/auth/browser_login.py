"""Playwright browser login (sync) — safe to run in a subprocess only."""

from __future__ import annotations

import os
from pathlib import Path

from app.config import get_settings
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


def configure_playwright_env() -> Path:
    """Point Playwright at the project browser cache (required on Render)."""
    settings = get_settings()
    browsers_path = settings.playwright_browsers_path.resolve()
    browsers_path.mkdir(parents=True, exist_ok=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_path)
    return browsers_path


def is_playwright_browser_installed() -> bool:
    """True if Chromium was installed (e.g. via playwright install in build)."""
    browsers_path = configure_playwright_env()
    if not browsers_path.exists():
        return False
    markers = (
        "chrome-headless-shell",
        "chrome",
        "chromium",
    )
    return any(
        marker in child.name.lower()
        for child in browsers_path.rglob("*")
        if child.is_file()
        for marker in markers
    )


def run_browser_login(email: str, password: str) -> dict:
    """Return {"cookies": {...}, "csrf_token": str | None}. Raises on failure."""
    if not is_playwright_browser_installed():
        raise RuntimeError(
            "Playwright Chromium is not installed. On Render, set build command to: "
            "pip install -r requirements.txt && "
            "PLAYWRIGHT_BROWSERS_PATH=$PWD/.playwright-browsers "
            "playwright install --with-deps chromium"
        )

    settings = get_settings()
    configure_playwright_env()
    base_url = settings.chartink_base_url.rstrip("/")
    cookies: dict[str, str] = {}
    csrf_token: str | None = None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=settings.playwright_headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.set_default_timeout(settings.playwright_timeout_ms)
        page.goto(f"{base_url}/login", wait_until="domcontentloaded")

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
                timeout=settings.playwright_timeout_ms,
            )
        except PlaywrightTimeoutError:
            if "/login" in page.url:
                raise RuntimeError(
                    "Login did not complete (Chartink may require reCAPTCHA on this IP). "
                    "Retry POST /refresh-session or check Render logs."
                ) from None

        for cookie in context.cookies():
            cookies[cookie["name"]] = cookie["value"]

        try:
            csrf_meta = page.locator("meta[name='csrf-token']").first
            if csrf_meta.count():
                csrf_token = csrf_meta.get_attribute("content")
        except Exception:
            pass

        browser.close()

    if "ci_session" not in cookies:
        raise RuntimeError("ci_session cookie missing after login")

    return {"cookies": cookies, "csrf_token": csrf_token}
