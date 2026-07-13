"""Internal job endpoints (Render Cron / authenticated ops)."""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from loguru import logger

from app.config import get_settings
from app.dependencies import get_chartink_client, get_repository, get_session_manager
from providers.chartink_provider import ChartinkProvider
from providers.marketsmith_provider import MarketSmithProvider
from services.collection_service import CollectionService

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _authorized(cron_secret: str | None, webhook_secret: str | None) -> bool:
    settings = get_settings()
    expected = (settings.cron_secret or settings.webhook_secret or "").strip()
    if not expected:
        return False
    provided = (cron_secret or webhook_secret or "").strip()
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)


def _seed_scan_slugs(repository) -> None:
    """Upsert optional name→slug mappings so friendly COLLECTION_SCAN_NAMES resolve."""
    settings = get_settings()
    for name, slug in settings.get_collection_scan_slugs().items():
        url = f"https://chartink.com/screener/{slug}"
        repository.upsert_scan(name=name, slug=slug, url=url)
        logger.info("Seeded scan mapping: {} -> {}", name, slug)


@router.post("/collect-daily")
def collect_daily(
    x_cron_secret: str | None = Header(default=None, alias="X-Cron-Secret"),
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
    idempotent: bool = True,
) -> dict[str, Any]:
    """
    Run the Phase 1 daily collector on this web service (same SQLite / cookies).

    Render Cron should call this URL so history lands next to the MCP process.
    Auth: header ``X-Cron-Secret`` (or ``X-Webhook-Secret``) must match
    ``CRON_SECRET`` (falls back to ``WEBHOOK_SECRET``).
    """
    if not _authorized(x_cron_secret, x_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid or missing cron secret")

    settings = get_settings()
    scan_names = settings.get_collection_scan_names()
    if not scan_names:
        raise HTTPException(
            status_code=400,
            detail="COLLECTION_SCAN_NAMES is empty — set it in the Render env",
        )

    repository = get_repository()
    try:
        _seed_scan_slugs(repository)
    except Exception as exc:
        logger.warning("Scan slug seeding skipped/failed: {}", exc)

    session_manager = get_session_manager()
    session_manager.load_cookies()
    if settings.chartink_auto_login:
        try:
            session_manager.try_startup_login()
        except Exception as exc:
            logger.warning("Pre-collect login attempt failed: {}", exc)

    service = CollectionService(
        repository=repository,
        chartink_provider=ChartinkProvider(get_chartink_client()),
        marketsmith_provider=MarketSmithProvider(),
        scan_delay_seconds=settings.collection_scan_delay_seconds,
    )

    try:
        result = service.collect_daily_market_data(
            scan_names,
            idempotent_date=idempotent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Cron collection failed: {}", exc)
        raise HTTPException(status_code=500, detail=f"Collection failed: {exc}") from exc

    if result.get("status") == "failed":
        raise HTTPException(status_code=502, detail=result)

    return result
