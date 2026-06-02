#!/usr/bin/env python3
"""Test Chartink scan discovery and execution."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from auth.session_manager import SessionManager
from clients.chartink_client import ChartinkClient
from storage.database import get_session_factory, init_db
from storage.repository import ChartinkRepository


def main() -> int:
    init_db()
    repository = ChartinkRepository(get_session_factory())
    session_manager = SessionManager(repository=repository)
    client = ChartinkClient(session_manager=session_manager, repository=repository)

    print("Chartink Scan Test")
    print("-" * 40)

    try:
        session_manager.auto_reauthenticate()
        print("✓ Login successful")
    except Exception as exc:
        print(f"✗ Login failed: {exc}")
        return 1

    if session_manager.validate_session():
        print("✓ Session valid")
    else:
        print("✗ Session invalid")
        return 1

    scans = client.get_all_scans(sync_db=True)
    print(f"✓ Found {len(scans)} scans")
    if not scans:
        print("⚠ No scans found — account may have no saved scans")
        return 0

    target = scans[0]
    print(f"  Running scan: {target['name']}")

    try:
        result = client.run_scan_by_url(target["url"], scan_name=target["name"])
        print("✓ Scan executed")
        print(f"✓ Results returned ({result['records_total']} records)")
        if result["results"]:
            sample = result["results"][0]
            symbol = sample.get("nsecode") or sample.get("bsecode") or "N/A"
            print(f"  Sample: {symbol} @ {sample.get('close')} ({sample.get('per_chg')}%)")
    except Exception as exc:
        print(f"✗ Scan execution failed: {exc}")
        return 1

    print("-" * 40)
    print("All scan tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
