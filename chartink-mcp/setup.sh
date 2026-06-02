#!/usr/bin/env bash
# One-time project setup (macOS-friendly — uses python3, not python).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if command -v python3 &>/dev/null; then
  PYTHON=python3
elif command -v python &>/dev/null; then
  PYTHON=python
else
  echo "Error: Python 3 is not installed."
  echo "Install from https://www.python.org/downloads/ or run: brew install python"
  exit 1
fi

echo "Using: $($PYTHON --version)"
$PYTHON -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — add your Chartink credentials."
fi

chmod +x run setup.sh
echo ""
echo "Setup complete. Examples:"
echo "  ./run scripts/login_test.py"
echo "  .venv/bin/uvicorn app.server:app --reload --port 8000"
