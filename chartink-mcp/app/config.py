"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from loguru import logger
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def ensure_writable_data_dir(raw: str | Path) -> Path:
    """Resolve and ensure a writable data directory (Render-safe fallback to /tmp)."""
    data_dir = Path(raw)
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write_probe"
        probe.touch()
        probe.unlink(missing_ok=True)
        return data_dir.resolve()
    except OSError as exc:
        fallback = Path("/tmp")
        fallback.mkdir(parents=True, exist_ok=True)
        logger.warning("DATA_DIR {} not writable ({}); using {}", data_dir, exc, fallback)
        return fallback.resolve()


def get_data_dir() -> Path:
    """Writable storage root: process DATA_DIR env, else /tmp."""
    return ensure_writable_data_dir(os.getenv("DATA_DIR", "/tmp"))


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

    data_dir: Path = Field(default=Path("/tmp"), alias="DATA_DIR")
    database_url: str = "sqlite:////tmp/chartink.db"
    cookies_file: Path = Path("/tmp/cookies.json")
    findings_file: Path = Path("/tmp/inspection_findings.json")

    session_refresh_interval_minutes: int = 30
    request_timeout_seconds: int = 30
    max_scan_results: int = 500

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
    playwright_browsers_path: Path = Field(
        default=PROJECT_ROOT / ".playwright-browsers",
        alias="PLAYWRIGHT_BROWSERS_PATH",
    )

    webhook_secret: str = Field(default="", alias="WEBHOOK_SECRET")
    cron_secret: str = Field(default="", alias="CRON_SECRET")
    log_level: str = "INFO"

    atlas_default_dashboard: str = Field(
        default="5IvaWealth Advanced",
        alias="ATLAS_DEFAULT_DASHBOARD",
    )

    # Daily collector: comma-separated Chartink scan names (required for collection).
    collection_scan_names: str = Field(
        default="",
        alias="COLLECTION_SCAN_NAMES",
    )
    collection_scan_delay_seconds: float = Field(
        default=1.0,
        alias="COLLECTION_SCAN_DELAY_SECONDS",
    )
    # Optional friendly-name → screener slug map (comma-separated name:slug pairs).
    # Example: Volume 3X Weekly:volume-3-times-the-average-on-weekly-tf,Volume 3X Daily:volume-2x-daily
    collection_scan_slugs: str = Field(
        default="",
        alias="COLLECTION_SCAN_SLUGS",
    )

    @model_validator(mode="after")
    def resolve_storage_paths(self) -> Self:
        # Prefer OS env; otherwise honor DATA_DIR from .env via Settings field.
        raw = os.getenv("DATA_DIR") or str(self.data_dir)
        self.data_dir = ensure_writable_data_dir(raw)
        self.cookies_file = self.data_dir / "cookies.json"
        self.findings_file = self.data_dir / "inspection_findings.json"
        self.database_url = f"sqlite:///{self.data_dir / 'chartink.db'}"
        return self

    def get_collection_scan_names(self) -> list[str]:
        """Parse COLLECTION_SCAN_NAMES into a clean list."""
        if not self.collection_scan_names.strip():
            return []
        return [
            name.strip()
            for name in self.collection_scan_names.split(",")
            if name.strip()
        ]

    def get_collection_scan_slugs(self) -> dict[str, str]:
        """Parse COLLECTION_SCAN_SLUGS into {scan_name: slug}."""
        mapping: dict[str, str] = {}
        raw = self.collection_scan_slugs.strip()
        if not raw:
            return mapping
        for part in raw.split(","):
            part = part.strip()
            if not part or ":" not in part:
                continue
            name, slug = part.split(":", 1)
            name, slug = name.strip(), slug.strip()
            if name and slug:
                mapping[name] = slug
        return mapping


@lru_cache
def get_settings() -> Settings:
    return Settings()
