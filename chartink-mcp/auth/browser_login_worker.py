"""Isolated subprocess entrypoint for Playwright sync login (no asyncio loop)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auth.browser_login import run_browser_login  # noqa: E402


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: browser_login_worker.py <email> <password>", file=sys.stderr)
        return 1
    email, password = sys.argv[1], sys.argv[2]
    try:
        payload = run_browser_login(email, password)
        print(json.dumps(payload))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
