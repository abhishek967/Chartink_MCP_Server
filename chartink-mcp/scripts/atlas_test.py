#!/usr/bin/env python3
"""Test Chartink Atlas dashboard stock extraction."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from clients.atlas_client import AtlasClient
from storage.database import get_session_factory, init_db
from storage.repository import ChartinkRepository


def main() -> int:
    settings = get_settings()
    init_db()
    repository = ChartinkRepository(get_session_factory())
    atlas = AtlasClient(repository=repository)

    print("Chartink Atlas Dashboard Test")
    print("-" * 50)
    print(f"Target dashboard: {settings.atlas_default_dashboard}")

    dashboards = atlas.get_user_dashboards()
    print(f"✓ Found {len(dashboards)} Atlas dashboards")

    widgets_payload = atlas.get_dashboard_widgets(settings.atlas_default_dashboard)
    widgets = widgets_payload.get("widgets", [])
    print(f"✓ Loaded {len(widgets)} widgets")

    result = atlas.run_dashboard(settings.atlas_default_dashboard, cache=True)
    for widget in result.get("widgets", []):
        widget.pop("raw", None)

    print(f"✓ Executed dashboard: {result['dashboard_name']} (id={result['dashboard_id']})")
    print(f"✓ Merged unique stocks: {result['merged_symbol_count']}")
    print(f"✓ High conviction (2+ widgets): {len(result['high_conviction'])}")

    output_path = PROJECT_ROOT / "data" / "atlas_5ivawealth_stocks.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"✓ Saved full report to {output_path}")

    print("\nTop high-conviction stocks:")
    for item in result["high_conviction"][:15]:
        print(f"  - {item['symbol']} (widgets={item['widget_hits']}, score={item['conviction_score']})")

    print("\nSample merged stocks:")
    for symbol in result["merged_symbols"][:30]:
        print(f"  - {symbol}")
    if result["merged_symbol_count"] > 30:
        print(f"  ... and {result['merged_symbol_count'] - 30} more")

    print("-" * 50)
    print("All Atlas tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
