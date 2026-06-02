"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Chartink Intelligence MCP"
    app_version: str = "1.0.0"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False

    host: str = "0.0.0.0"
    port: int = 8000

    chartink_base_url: str = "https://chartink.com"
    chartink_email: str = Field(default="", alias="CHARTINK_EMAIL")
    chartink_password: str = Field(default="", alias="CHARTINK_PASSWORD")

    database_url: str = Field(
        default=f"sqlite:///{PROJECT_ROOT / 'data' / 'chartink.db'}",
        alias="DATABASE_URL",
    )

    cookies_file: Path = Field(
        default=PROJECT_ROOT / "data" / "cookies.json",
        alias="COOKIES_FILE",
    )
    findings_file: Path = Field(
        default=PROJECT_ROOT / "data" / "inspection_findings.json",
        alias="FINDINGS_FILE",
    )

    session_refresh_interval_minutes: int = 30
    request_timeout_seconds: int = 30
    max_scan_results: int = 500

    # Automated browser login (runs in a subprocess, safe with asyncio).
    chartink_auto_login: bool = Field(
        default=True,
        alias="CHARTINK_AUTO_LOGIN",
    )
    chartink_startup_auto_login: bool = Field(
        default=True,
        alias="CHARTINK_STARTUP_AUTO_LOGIN",
    )

    playwright_headless: bool = True
    playwright_timeout_ms: int = 60_000

    webhook_secret: str = Field(default="", alias="WEBHOOK_SECRET")
    log_level: str = "INFO"

    atlas_default_dashboard: str = Field(
        default="5IvaWealth Advanced",
        alias="ATLAS_DEFAULT_DASHBOARD",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
