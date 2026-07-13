#!/usr/bin/env bash
# Phase 2 — Render Cron entrypoint.
# Calls the web service so collection writes to the same DATA_DIR / SQLite.
set -euo pipefail

URL="${COLLECT_URL:-https://chartink-mcp-server-2.onrender.com/jobs/collect-daily}"
SECRET="${CRON_SECRET:-${WEBHOOK_SECRET:-}}"

if [[ -z "$SECRET" ]]; then
  echo "CRON_SECRET (or WEBHOOK_SECRET) must be set" >&2
  exit 2
fi

echo "Triggering daily collection at $URL"
HTTP_CODE=$(curl -sS -o /tmp/collect_response.json -w "%{http_code}" \
  -X POST \
  -H "Content-Type: application/json" \
  -H "X-Cron-Secret: ${SECRET}" \
  --max-time 300 \
  "${URL}?idempotent=true")

echo "HTTP ${HTTP_CODE}"
cat /tmp/collect_response.json || true
echo

if [[ "$HTTP_CODE" -lt 200 || "$HTTP_CODE" -ge 300 ]]; then
  exit 1
fi

exit 0
