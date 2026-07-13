#!/usr/bin/env python3
"""Phase 1 verification: schema, score engine, duplicate prevention (no FastMCP import)."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    from app.config import get_settings
    from providers.base import StockObservation
    from services.score_engine import calculate_stock_score
    from services.collection_service import merge_scan_rows
    from providers.base import ScanHitRow
    from storage.database import init_db, get_session_factory
    from storage.models import CollectionRun, MarketSignal
    from storage.repository import ChartinkRepository

    get_settings.cache_clear()
    settings = get_settings()
    print(f"DATA_DIR={settings.data_dir}")
    print(f"DB={settings.database_url}")

    init_db()
    repo = ChartinkRepository(get_session_factory())

    obs = StockObservation(
        symbol="TESTCO",
        company_name="Test Co",
        sector="Technology",
        close_price=100.0,
        per_chg=2.5,
        volume=750_000,
        triggered_scans=["Scan A", "Scan B"],
        scan_count=2,
    )
    scored = calculate_stock_score(obs)
    assert scored["final_score"] > 0
    assert "score_breakdown" in scored
    print(f"✓ Score engine: final_score={scored['final_score']}")

    merged = merge_scan_rows(
        [
            (
                "Scan A",
                [ScanHitRow(symbol="AAA", close_price=10, per_chg=1, volume=100)],
            ),
            (
                "Scan B",
                [
                    ScanHitRow(symbol="AAA", close_price=11, per_chg=2, volume=200),
                    ScanHitRow(symbol="BBB", close_price=20, per_chg=0, volume=50),
                ],
            ),
        ]
    )
    assert merged["AAA"].scan_count == 2
    assert set(merged["AAA"].triggered_scans) == {"Scan A", "Scan B"}
    assert merged["BBB"].scan_count == 1
    print("✓ Scan merge / intersection OK")

    run_uuid = str(uuid.uuid4())
    run = repo.create_collection_run(
        run_uuid=run_uuid,
        collection_date="2099-01-01",
        scans_configured=["Scan A", "Scan B"],
    )
    first = repo.save_market_signal(
        run.id,
        symbol="TESTCO",
        company_name="Test Co",
        sector="Technology",
        close_price=100.0,
        triggered_scans=["Scan A", "Scan B"],
        scan_count=2,
        score_breakdown=scored["score_breakdown"],
        final_score=scored["final_score"],
    )
    assert first is not None
    dup = repo.save_market_signal(
        run.id,
        symbol="TESTCO",
        company_name="Test Co",
        sector="Technology",
        close_price=101.0,
        triggered_scans=["Scan A"],
        scan_count=1,
        score_breakdown=scored["score_breakdown"],
        final_score=scored["final_score"],
    )
    assert dup is None
    assert repo.count_signals_for_run(run.id) == 1
    print(f"✓ Duplicate prevention works (run_id={run.id})")

    repo.complete_collection_run(
        run.id,
        scans_succeeded=2,
        scans_failed=0,
        stocks_saved=1,
        execution_seconds=0.1,
        summary={"test": True},
        status="completed",
    )
    existing = repo.get_completed_run_for_date("2099-01-01")
    assert existing is not None and existing.run_uuid == run_uuid
    print("✓ Collection run lifecycle OK")

    assert CollectionRun.__tablename__ == "collection_runs"
    assert MarketSignal.__tablename__ == "market_signals"
    print("✓ Models collection_runs / market_signals present")

    print("\nPhase 1 verification passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
