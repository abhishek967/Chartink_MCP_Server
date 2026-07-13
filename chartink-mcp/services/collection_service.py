"""Daily market collection orchestration (provider + score + persist)."""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from providers.base import MarketDataProvider, ScanHitRow, StockObservation
from providers.marketsmith_provider import MarketSmithProvider
from services.score_engine import calculate_stock_score
from storage.repository import ChartinkRepository

IST = ZoneInfo("Asia/Kolkata")


def ist_collection_date() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def merge_scan_rows(
    scan_results: list[tuple[str, list[ScanHitRow]]],
) -> dict[str, StockObservation]:
    """Merge per-scan rows into one StockObservation per symbol."""
    by_symbol: dict[str, dict[str, Any]] = {}

    for scan_name, rows in scan_results:
        for row in rows:
            symbol = row.symbol.upper().strip()
            if not symbol:
                continue
            entry = by_symbol.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "company_name": row.company_name,
                    "sector": row.sector,
                    "close_price": row.close_price,
                    "per_chg": row.per_chg,
                    "volume": row.volume,
                    "scans": [],
                },
            )
            if scan_name not in entry["scans"]:
                entry["scans"].append(scan_name)
            if row.company_name and not entry.get("company_name"):
                entry["company_name"] = row.company_name
            if row.sector and not entry.get("sector"):
                entry["sector"] = row.sector
            if row.close_price and (not entry.get("close_price") or row.close_price > 0):
                entry["close_price"] = row.close_price
            if row.per_chg is not None:
                # Keep strongest absolute move for scoring context
                prev = entry.get("per_chg")
                if prev is None or abs(row.per_chg) > abs(prev):
                    entry["per_chg"] = row.per_chg
            if row.volume and (not entry.get("volume") or row.volume > (entry.get("volume") or 0)):
                entry["volume"] = row.volume

    observations: dict[str, StockObservation] = {}
    for symbol, data in by_symbol.items():
        observations[symbol] = StockObservation(
            symbol=symbol,
            company_name=data.get("company_name"),
            sector=data.get("sector"),
            close_price=data.get("close_price"),
            per_chg=data.get("per_chg"),
            volume=data.get("volume"),
            triggered_scans=list(data.get("scans") or []),
            scan_count=len(data.get("scans") or []),
        )
    return observations


class CollectionService:
    """
    Orchestrates daily collection: auth → scans → merge → score → persist.

    Independent of MCP; callable from CLI, cron, or thin MCP wrappers later.
    """

    def __init__(
        self,
        repository: ChartinkRepository,
        chartink_provider: MarketDataProvider,
        marketsmith_provider: MarketDataProvider | None = None,
        scan_delay_seconds: float = 1.0,
    ) -> None:
        self.repository = repository
        self.chartink = chartink_provider
        self.marketsmith = marketsmith_provider or MarketSmithProvider()
        self.scan_delay_seconds = max(0.0, scan_delay_seconds)

    def collect_daily_market_data(
        self,
        scan_names: list[str],
        *,
        collection_date: str | None = None,
        idempotent_date: bool = False,
    ) -> dict[str, Any]:
        """
        Run configured scans, score merged stocks, and persist market_signals.

        Returns a structured summary suitable for logging and CLI exit handling.
        """
        started = time.monotonic()
        collection_date = collection_date or ist_collection_date()
        scan_names = [n.strip() for n in scan_names if n and n.strip()]

        if not scan_names:
            raise ValueError(
                "No scans configured. Set COLLECTION_SCAN_NAMES to a comma-separated "
                "list of Chartink scan names."
            )

        logger.info("Collection Started")
        logger.info("Collection Date: {}", collection_date)

        if idempotent_date:
            existing = self.repository.get_completed_run_for_date(collection_date)
            if existing is not None:
                logger.info(
                    "Idempotent skip: completed run {} already exists for {}",
                    existing.run_uuid,
                    collection_date,
                )
                return {
                    "skipped": True,
                    "reason": "completed_run_exists",
                    "run_uuid": existing.run_uuid,
                    "run_id": existing.id,
                    "collection_date": collection_date,
                    "stocks_saved": existing.stocks_saved,
                    "status": "skipped",
                }

        run_uuid = str(uuid.uuid4())
        logger.info("Run ID: {}", run_uuid)

        run = self.repository.create_collection_run(
            run_uuid=run_uuid,
            collection_date=collection_date,
            scans_configured=scan_names,
        )

        try:
            self.chartink.ensure_authenticated()
        except Exception as exc:
            elapsed = time.monotonic() - started
            msg = f"Authentication failed: {exc}"
            logger.error(msg)
            self.repository.complete_collection_run(
                run.id,
                scans_succeeded=0,
                scans_failed=len(scan_names),
                stocks_saved=0,
                execution_seconds=elapsed,
                summary={"error": msg},
                error_message=msg,
                status="failed",
            )
            return {
                "skipped": False,
                "status": "failed",
                "run_uuid": run_uuid,
                "run_id": run.id,
                "collection_date": collection_date,
                "error": msg,
                "execution_seconds": round(elapsed, 2),
            }

        scan_payloads: list[tuple[str, list[ScanHitRow]]] = []
        scan_summaries: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0

        for index, scan_name in enumerate(scan_names):
            logger.info("Running Scan: {}", scan_name)
            result = self.chartink.run_scan(scan_name)
            if result.success:
                succeeded += 1
                logger.info("Stocks Returned: {}", len(result.rows))
                scan_payloads.append((scan_name, result.rows))
                scan_summaries.append(
                    {
                        "scan_name": scan_name,
                        "success": True,
                        "stocks_returned": len(result.rows),
                        "records_total": result.records_total,
                    }
                )
            else:
                failed += 1
                logger.error("Scan Failed: {} — {}", scan_name, result.error)
                scan_summaries.append(
                    {
                        "scan_name": scan_name,
                        "success": False,
                        "error": result.error,
                        "stocks_returned": 0,
                    }
                )

            if index < len(scan_names) - 1 and self.scan_delay_seconds > 0:
                time.sleep(self.scan_delay_seconds)

        logger.info("Calculating Scores...")
        observations = merge_scan_rows(scan_payloads)

        # Optional MarketSmith enrichment (no-op stub today)
        for symbol, obs in list(observations.items()):
            observations[symbol] = self.marketsmith.enrich_observation(obs)

        logger.info("Saving Database...")
        saved = 0
        duplicates_skipped = 0
        top_preview: list[dict[str, Any]] = []

        for symbol, obs in observations.items():
            scored = calculate_stock_score(obs)
            signal = self.repository.save_market_signal(
                run.id,
                symbol=obs.symbol,
                company_name=obs.company_name,
                sector=obs.sector,
                close_price=obs.close_price,
                triggered_scans=obs.triggered_scans,
                scan_count=obs.scan_count,
                score_breakdown=scored["score_breakdown"],
                final_score=scored["final_score"],
                rs_rating=obs.rs_rating,
                eps_rating=obs.eps_rating,
                composite_rating=obs.composite_rating,
                industry_rank=obs.industry_rank,
                accumulation_distribution=obs.accumulation_distribution,
                pattern_type=obs.pattern_type,
                market_outlook=obs.market_outlook,
            )
            if signal is None:
                duplicates_skipped += 1
            else:
                saved += 1
                top_preview.append(
                    {
                        "symbol": symbol,
                        "final_score": scored["final_score"],
                        "scan_count": obs.scan_count,
                        "scans": obs.triggered_scans,
                    }
                )

        top_preview.sort(key=lambda x: x["final_score"], reverse=True)
        elapsed = time.monotonic() - started
        status = "completed" if succeeded > 0 else "failed"
        summary = {
            "scans": scan_summaries,
            "unique_symbols": len(observations),
            "duplicates_skipped": duplicates_skipped,
            "top_symbols": top_preview[:20],
        }

        self.repository.complete_collection_run(
            run.id,
            scans_succeeded=succeeded,
            scans_failed=failed,
            stocks_saved=saved,
            execution_seconds=elapsed,
            summary=summary,
            error_message=None if succeeded > 0 else "All configured scans failed",
            status=status,
        )

        logger.info("Collection Completed")
        logger.info("Execution Time: {:.2f} sec", elapsed)
        logger.info("Records Saved: {}", saved)
        if duplicates_skipped:
            logger.info("Duplicates Skipped: {}", duplicates_skipped)

        return {
            "skipped": False,
            "status": status,
            "run_uuid": run_uuid,
            "run_id": run.id,
            "collection_date": collection_date,
            "scans_configured": scan_names,
            "scans_succeeded": succeeded,
            "scans_failed": failed,
            "unique_symbols": len(observations),
            "stocks_saved": saved,
            "duplicates_skipped": duplicates_skipped,
            "execution_seconds": round(elapsed, 2),
            "summary": summary,
        }
