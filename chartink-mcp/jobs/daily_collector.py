#!/usr/bin/env python3
"""
Daily market collector — standalone CLI (no MCP dependency).

Usage:
  python jobs/daily_collector.py
  python jobs/daily_collector.py --idempotent-date
  python jobs/daily_collector.py --scan-names "Scan A,Scan B"

Requires COLLECTION_SCAN_NAMES (or --scan-names) and Chartink credentials.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger

from app.config import get_settings
from app.dependencies import get_chartink_client, get_repository, get_session_manager
from providers.chartink_provider import ChartinkProvider
from providers.marketsmith_provider import MarketSmithProvider
from services.collection_service import CollectionService
from storage.database import init_db


def configure_logging(level: str) -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<level>{message}</level>"
        ),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect daily Chartink market signals")
    parser.add_argument(
        "--scan-names",
        type=str,
        default="",
        help="Comma-separated scan names (overrides COLLECTION_SCAN_NAMES)",
    )
    parser.add_argument(
        "--collection-date",
        type=str,
        default="",
        help="Override collection date YYYY-MM-DD (default: today IST)",
    )
    parser.add_argument(
        "--idempotent-date",
        action="store_true",
        help="Skip if a completed run already exists for the collection date",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    # Clear settings cache so CLI always sees current env
    get_settings.cache_clear()
    settings = get_settings()
    configure_logging(settings.log_level)

    scan_names = (
        [n.strip() for n in args.scan_names.split(",") if n.strip()]
        if args.scan_names.strip()
        else settings.get_collection_scan_names()
    )

    if not scan_names:
        logger.error(
            "No scans configured. Set COLLECTION_SCAN_NAMES or pass --scan-names."
        )
        return 2

    init_db()

    # Ensure session manager can load cookies / login
    session_manager = get_session_manager()
    session_manager.load_cookies()
    if settings.chartink_auto_login:
        try:
            session_manager.try_startup_login()
        except Exception as exc:
            logger.warning("Startup login attempt failed (will retry on first scan): {}", exc)

    repository = get_repository()
    for name, slug in settings.get_collection_scan_slugs().items():
        repository.upsert_scan(
            name=name,
            slug=slug,
            url=f"https://chartink.com/screener/{slug}",
        )
        logger.info("Seeded scan mapping: {} -> {}", name, slug)

    service = CollectionService(
        repository=repository,
        chartink_provider=ChartinkProvider(get_chartink_client()),
        marketsmith_provider=MarketSmithProvider(),
        scan_delay_seconds=settings.collection_scan_delay_seconds,
    )

    try:
        result = service.collect_daily_market_data(
            scan_names,
            collection_date=args.collection_date or None,
            idempotent_date=args.idempotent_date,
        )
    except ValueError as exc:
        logger.error("{}", exc)
        return 2
    except Exception as exc:
        logger.exception("Collection failed: {}", exc)
        return 1

    if result.get("skipped"):
        logger.info("Collector exited cleanly (skipped)")
        return 0

    if result.get("status") == "failed":
        logger.error("Collection finished with status=failed")
        return 1

    logger.info(
        "Done: run_uuid={} stocks_saved={} scans_ok={}/{}",
        result.get("run_uuid"),
        result.get("stocks_saved"),
        result.get("scans_succeeded"),
        len(result.get("scans_configured") or []),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
