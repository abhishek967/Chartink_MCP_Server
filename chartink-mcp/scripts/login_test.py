#!/usr/bin/env python3
"""Test Chartink login and session validation."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from auth.session_manager import SessionManager
from storage.database import get_session_factory, init_db
from storage.repository import ChartinkRepository


def main() -> int:
    init_db()
    repository = ChartinkRepository(get_session_factory())
    session_manager = SessionManager(repository=repository)

    print("Chartink Login Test")
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

    cookies = session_manager.get_cookies()
    print(f"✓ Cookies loaded ({len(cookies)} cookies)")
    print("-" * 40)
    print("All login tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
