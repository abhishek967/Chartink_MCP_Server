#!/usr/bin/env bash
# Render native Python build — installs deps + Chromium into the project tree.
set -euo pipefail
cd "$(dirname "$0")/.."

export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$PWD/.playwright-browsers}"

pip install -r requirements.txt
playwright install --with-deps chromium

echo "Playwright browsers installed at: $PLAYWRIGHT_BROWSERS_PATH"
