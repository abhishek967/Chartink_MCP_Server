#!/usr/bin/env python3
"""Inspect Chartink authenticated endpoints and save findings."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from auth.session_manager import SessionManager
from clients.chartink_client import ChartinkClient
from storage.database import init_db
from storage.repository import ChartinkRepository
from storage.database import get_session_factory


def main() -> int:
    settings = get_settings()
    init_db()
    repository = ChartinkRepository(get_session_factory())
    session_manager = SessionManager(repository=repository)
    client = ChartinkClient(session_manager=session_manager, repository=repository)

    print("=" * 60)
    print("Chartink Intelligence — Inspection Script")
    print("=" * 60)

    print("\n[1/5] Logging in to Chartink...")
    try:
        cookies = session_manager.auto_reauthenticate()
        print(f"✓ Login successful ({len(cookies)} cookies)")
    except Exception as exc:
        print(f"✗ Login failed: {exc}")
        return 1

    print("\n[2/5] Authenticated cookies:")
    for name, value in cookies.items():
        display = value[:20] + "..." if len(value) > 20 else value
        print(f"  • {name}: {display}")

    print("\n[3/5] Discovering endpoints...")
    findings = client.discover_endpoints()
    for endpoint in findings["endpoints"]:
        status = "✓" if endpoint.get("reachable") else "✗"
        print(
            f"  {status} {endpoint['name']}: {endpoint['path']} "
            f"[{endpoint.get('status_code', 'N/A')}]"
        )

    print("\n[4/5] Fetching accessible scans...")
    scans = client.get_all_scans(sync_db=True)
    print(f"✓ Found {len(scans)} scans")
    for scan in scans[:20]:
        print(f"  • {scan['name']} → {scan['url']}")
    if len(scans) > 20:
        print(f"  ... and {len(scans) - 20} more")

    print("\n[5/5] Scan metadata sample...")
    scan_metadata = []
    for scan in scans[:5]:
        meta = {
            "name": scan["name"],
            "slug": scan["slug"],
            "url": scan["url"],
            "scan_clause": scan.get("scan_clause"),
            "metadata": scan.get("metadata"),
        }
        scan_metadata.append(meta)
        print(f"  • {scan['name']}: slug={scan['slug']}")

    output = {
        "cookies": list(cookies.keys()),
        "endpoints": findings["endpoints"],
        "scans_count": len(scans),
        "scans": scans,
        "scan_metadata_sample": scan_metadata,
        "profile": client.get_profile() if session_manager.validate_session() else {},
    }

    settings.findings_file.parent.mkdir(parents=True, exist_ok=True)
    settings.findings_file.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
    print(f"\n✓ Findings saved to {settings.findings_file}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
