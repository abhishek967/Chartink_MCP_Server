# Chartink Intelligence MCP

Production-grade MCP server that gives Claude / ChatGPT authenticated access to your Chartink account — Atlas dashboards, scans, alerts, watchlists, and cross-scan market analysis — plus a **Phase 1 daily market collector** that writes historical signals into SQLite.

**Live app:** [https://chartink-mcp-server-2.onrender.com](https://chartink-mcp-server-2.onrender.com)  
**MCP URL:** `https://chartink-mcp-server-2.onrender.com/mcp` (Streamable HTTP, no OAuth)

---

## What has been done (status)

### Live on Render today

| Area | Status |
|------|--------|
| FastAPI + FastMCP server | Live (`/health` → ok) |
| Chartink session / cookies | Authenticated |
| Atlas REST + MCP tools | Working |
| Existing Claude/ChatGPT MCP flow | Unchanged and working |
| Phase 1 collector **code** on `main` | Deployed (schema, services, CLI) |
| Phase 2 Cron wiring | In repo (`render.yaml` + `POST /jobs/collect-daily`) — enable Cron + `CRON_SECRET` in dashboard |

### Verified locally (manual Phase 1 test)

| Check | Result |
|-------|--------|
| Collector CLI `jobs/daily_collector.py` | Ran successfully (4/4 scans) |
| SQLite writes | `collection_runs` + `market_signals` (783 rows on test day) |
| Duplicate prevention `--idempotent-date` | Skips if a completed run already exists for that date |
| MCP still healthy after collector | Confirmed against live `/mcp` |

**DB path (local):** `chartink-mcp/data/chartink.db`  
**DB path (Render default today):** `/tmp/chartink.db` (ephemeral unless you mount a persistent disk + set `DATA_DIR`)

### Not finished yet / dashboard steps

| Item | Notes |
|------|--------|
| Create/sync Cron service in Render | Use blueprint or add Cron Job manually (`scripts/trigger_collect.sh`) |
| Set `CRON_SECRET` on web + cron | Required for `POST /jobs/collect-daily` |
| Persistent `DATA_DIR` | Recommended so history survives deploys |
| Equimantum 90-day as a collector scan | Atlas widget only — no public `/screener/...` URL yet |

---

## Architecture

```
Claude / ChatGPT (MCP)          Cron / CLI (Phase 2)
         │                              │
         ▼                              ▼
   FastMCP /mcp                 jobs/daily_collector.py
         │                              │
         └──────────┬───────────────────┘
                    ▼
         Chartink client + Atlas client
                    │
         Session Manager (Playwright + cookies)
                    │
         SQLite (chartink.db) — scans, atlas cache, collection_runs, market_signals
```

## Features

- Browser-based Chartink login with persistent session cookies
- Automatic session validation and re-authentication
- Atlas dashboard run / high-conviction stocks (MCP + REST)
- Scan discovery, execution, and historical result storage
- Alerts and watchlist sync
- Cross-scan conviction scoring and market summaries
- **Phase 1:** standalone daily collector → `collection_runs` / `market_signals`
- MCP tools + resources for Claude / ChatGPT
- FastAPI REST endpoints for health, Atlas, scans, and webhooks
- Render-ready (native Python build via `scripts/render_build.sh`)

## Phase 1 — Daily market collector

Independent of MCP. Reuses Chartink session + services and writes provider-agnostic scores into SQLite.

### Env

```env
DATA_DIR=data
COLLECTION_SCAN_NAMES=Volume 3X Weekly,Volume 3X Daily,Trend Template,EPS & Sales Growth
COLLECTION_SCAN_DELAY_SECONDS=1.0
CHARTINK_EMAIL=...
CHARTINK_PASSWORD=...
```

Scan names must resolve to Chartink **screener** pages (or rows already in the `scans` table). Atlas widget names alone are not enough.

### Run manually

```bash
cd chartink-mcp
.venv/bin/python jobs/daily_collector.py
.venv/bin/python jobs/daily_collector.py --idempotent-date
.venv/bin/python jobs/daily_collector.py --scan-names "Trend Template,EPS & Sales Growth"
```

### Verify SQLite

```bash
sqlite3 data/chartink.db
.tables
SELECT COUNT(*) FROM market_signals;
SELECT symbol, final_score, scan_count FROM market_signals ORDER BY final_score DESC LIMIT 10;
```

### Schema (high level)

- `collection_runs` — one row per collection job (`run_uuid`, `collection_date`, status, counts)
- `market_signals` — one row per symbol per run (`symbol`, `triggered_scans`, `scan_count`, `final_score`, …)

Offline unit check:

```bash
.venv/bin/python scripts/test_phase1_collector.py
```

**Phase 2 (next):** Render Cron Job calling the same CLI on a schedule — only after env + persistent `DATA_DIR` are set on Render.

## Phase 2 — Render Cron (daily collection)

Render Cron jobs have a **separate filesystem** from the web service. If Cron ran `python jobs/daily_collector.py` by itself, history would write to a different SQLite than MCP.

**Approach:** Cron HTTP-triggers the web service so data lands in the same `DATA_DIR`:

```text
Render Cron (weekdays 16:00 IST)
        │
        ▼
POST /jobs/collect-daily   (header X-Cron-Secret)
        │
        ▼
CollectionService → chartink.db on the web instance
```

### Schedule

| Item | Value |
|------|--------|
| Cron expression | `30 10 * * 1-5` |
| Meaning | Mon–Fri **16:00 IST** (10:30 UTC), after NSE cash close |
| Entrypoint | `scripts/trigger_collect.sh` → `POST /jobs/collect-daily?idempotent=true` |

Defined in `render.yaml` as service `chartink-daily-collector`.

### Render dashboard checklist

1. Set secrets on the **web** service:
   - `CHARTINK_EMAIL`, `CHARTINK_PASSWORD`
   - `CRON_SECRET` (long random string)
   - `COLLECTION_SCAN_NAMES` (and optional `COLLECTION_SCAN_SLUGS`)
2. Prefer a **persistent disk** for `DATA_DIR` (e.g. `/var/data`) so cookies + SQLite survive restarts (default blueprint uses `/tmp`).
3. Create / sync the Cron job from blueprint (`chartink-daily-collector`) with the **same** `CRON_SECRET`.
4. Manual smoke test:

```bash
curl -sS -X POST \
  -H "X-Cron-Secret: $CRON_SECRET" \
  "https://chartink-mcp-server-2.onrender.com/jobs/collect-daily?idempotent=true"
```

Idempotent mode skips if a **completed** run already exists for today’s IST date.

### Manual trigger still works

```bash
.venv/bin/python jobs/daily_collector.py --idempotent-date
```

## Quick Start

### 1. Configure environment

```bash
cd chartink-mcp
cp .env.example .env
# Edit .env with your CHARTINK_EMAIL and CHARTINK_PASSWORD
# Set DATA_DIR=data and COLLECTION_SCAN_NAMES for the collector
```

### 2. Run with Docker

```bash
docker-compose up --build
```

Server starts at `http://localhost:8000`.

### 3. Local development (without Docker)

On macOS, `python` is often missing — use `python3` or the helper scripts below.

```bash
./setup.sh          # creates .venv, installs deps (uses python3)
cp .env.example .env   # if setup.sh did not create .env

# Option A — helper script (recommended)
./run scripts/login_test.py

# Option B — activate venv (then `python` works inside the venv)
source .venv/bin/activate
python scripts/login_test.py

# Option C — call venv Python directly (no activate needed)
.venv/bin/python scripts/login_test.py

# Start server
.venv/bin/uvicorn app.server:app --reload --host 0.0.0.0 --port 8000
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service identity (liveness) |
| GET | `/health` | Lightweight liveness (`{"status":"ok"}`) |
| GET | `/health/detail` | Session and DB diagnostics |
| GET | `/scans` | List all account scans |
| GET | `/alerts` | List all alerts |
| GET | `/watchlists` | List all watchlists |
| POST | `/refresh-session` | Force session refresh |
| POST | `/webhook/chartink` | Receive Chartink alert webhooks |
| MCP | `/mcp` | MCP streamable HTTP endpoint |

## Atlas Dashboard (5IvaWealth Advanced)

This server can read your Chartink Atlas dashboards and return stocks from all widgets.

Flow:

`Chartink login -> Atlas user dashboards -> dashboard widgets -> /widget/process -> merged stocks`

### Atlas MCP tools

| Tool | Description |
|------|-------------|
| `get_atlas_dashboards` | List your Atlas dashboards |
| `get_atlas_dashboard_widgets` | Widgets on a dashboard |
| `run_atlas_dashboard` | Execute all widgets and return per-widget stocks |
| `get_atlas_dashboard_stocks` | Merged unique stock list |
| `get_atlas_high_conviction_stocks` | Stocks appearing in multiple widgets |

### Atlas REST endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/atlas/dashboards` | List dashboards |
| GET | `/atlas/dashboards/{name_or_id}/widgets` | Widget metadata |
| POST | `/atlas/dashboards/{name_or_id}/run` | Run dashboard |
| GET | `/atlas/dashboards/{name_or_id}/stocks` | Merged stocks |

### Test Atlas locally

```bash
./run scripts/atlas_test.py
```

Output is saved to `data/atlas_5ivawealth_stocks.json`.

Set default dashboard in `.env`:

```bash
ATLAS_DEFAULT_DASHBOARD=5IvaWealth Advanced
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `health_check` | Server and session health |
| `get_profile` | Authenticated user profile |
| `get_all_scans` | All account scans |
| `search_scans` | Search scans by keyword |
| `run_scan` | Execute a scan by name |
| `get_scan_results` | Latest cached or live results |
| `get_alerts` | Account alerts |
| `get_watchlists` | Account watchlists |
| `get_stock_details` | Stock details by symbol |
| `find_common_stocks` | Multi-scan symbol overlap |
| `rank_high_conviction_stocks` | Conviction-ranked stocks |
| `generate_market_summary` | Aggregate market summary |
| `generate_breakout_report` | Breakout analysis |
| `generate_swing_watchlist` | High-conviction watchlist |
| `get_top_momentum_stocks` | Top momentum picks |
| `find_sector_leaders` | Sector-grouped leaders |
| `calculate_conviction_score` | Score a single symbol |

## MCP Resources

- `chartink://scans` — Synced scan catalog
- `chartink://results` — Latest scan results
- `chartink://history` — Historical execution records
- `chartink://watchlists` — Synced watchlists
- `chartink://alerts` — Synced alerts

## Scripts

```bash
# Inspect Chartink endpoints and save findings
./run scripts/inspect_chartink.py

# Test login flow
./run scripts/login_test.py

# Test scan discovery and execution
./run scripts/scan_test.py
```

Expected test output:

```
✓ Login successful
✓ Session valid
✓ Found scans
✓ Scan executed
✓ Results returned
```

## ChatGPT / Claude MCP Integration

MCP URL (Streamable HTTP):

```text
https://your-app.onrender.com/mcp
```

### ChatGPT

1. Settings → Connectors → Add MCP Server
2. Paste the URL above (no trailing slash)

### Claude (claude.ai or Desktop)

This server does **not** implement OAuth. Chartink login is handled on the server via `CHARTINK_EMAIL` / `CHARTINK_PASSWORD`.

- **Do not** enter an OAuth Client ID unless you added OAuth to this project yourself.
- If Claude shows *"Couldn't register with … sign-in service"*, the connector is trying OAuth by mistake:
  - Choose **No authentication** / leave OAuth fields **empty**, or
  - Use **URL only** / **Streamable HTTP** transport with no auth.

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "chartink": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

**Claude Code** (terminal):

```bash
claude mcp add --transport http chartink https://your-app.onrender.com/mcp
```

Do not pass `--client-id` unless this server exposes OAuth (it does not).

## Webhook Setup

Configure Chartink alerts to POST to your deployed webhook:

```
https://your-app.onrender.com/webhook/chartink
```

Optional: set `WEBHOOK_SECRET` in `.env` and pass `X-Webhook-Secret` header.

Sample Chartink webhook payload:

```json
{
  "stocks": "RELIANCE,TCS,INFY",
  "trigger_prices": "2500.0,3800.0,1800.0",
  "triggered_at": "2:34 pm",
  "scan_name": "Short term breakouts",
  "scan_url": "short-term-breakouts",
  "alert_name": "Alert for Short term breakouts"
}
```

## Deploy to Render

1. Push this repo to GitHub
2. Create a new **Web Service** on [Render](https://render.com)
3. Connect your repository
4. Settings:
   - **Environment**: **Docker** (recommended — the Dockerfile runs `playwright install --with-deps chromium`)
   - **Dockerfile Path**: `Dockerfile`
   - **Health Check Path**: `/health` (or `/` — both return success without Chartink auth)
5. Add environment variables:
   - `CHARTINK_EMAIL`
   - `CHARTINK_PASSWORD`
   - `CHARTINK_STARTUP_AUTO_LOGIN=false` (default; keep off on Render)
   - `WEBHOOK_SECRET` (optional)
6. Add a **Persistent Disk** mounted at `/app/data` (for cookies + SQLite)
7. After deploy, authenticate once:
   - Run `scripts/login_test.py` locally and copy `data/cookies.json` to the disk, **or**
   - `POST https://your-app.onrender.com/refresh-session` (runs Playwright in a request worker; may still hit CAPTCHA)
8. Deploy

**Native Python on Render (not Docker):** add a build step so browsers exist:

```bash
pip install -r requirements.txt && playwright install --with-deps chromium
```

**Why startup login is off:** browser login uses Playwright’s sync API, which cannot run inside FastAPI’s asyncio lifespan. Startup auto-login is disabled by default so the service always boots; use persisted cookies or `/refresh-session` instead.

## Deploy to Railway

1. Push this repo to GitHub
2. Create a new project on [Railway](https://railway.app)
3. Deploy from GitHub repo
4. Railway auto-detects the Dockerfile
5. Add environment variables in the Railway dashboard:
   - `CHARTINK_EMAIL`
   - `CHARTINK_PASSWORD`
   - `PORT=8000`
6. Add a volume mounted at `/app/data` for persistence
7. Generate a public domain under Settings → Networking

## Project Structure

```
chartink-mcp/
├── app/
│   ├── server.py              # FastAPI + FastMCP entrypoint
│   ├── config.py              # Settings from .env (DATA_DIR, COLLECTION_SCAN_NAMES)
│   └── dependencies.py
├── clients/
│   ├── chartink_client.py     # Screener HTTP + CSRF-safe session
│   └── atlas_client.py
├── auth/
│   └── session_manager.py     # Playwright login + domain-scoped cookies
├── providers/                 # Phase 1: Chartink (+ MarketSmith stub)
├── services/
│   ├── collection_service.py  # Daily collection orchestration
│   └── score_engine.py
├── jobs/
│   └── daily_collector.py     # CLI collector (no MCP dependency)
├── storage/
│   ├── database.py
│   ├── models.py              # includes CollectionRun, MarketSignal
│   └── repository.py
├── analysis/
├── tools/                     # MCP tool registrations
├── routes/                    # REST: health, atlas, webhook
├── scripts/
│   ├── test_phase1_collector.py
│   ├── render_build.sh
│   └── ...
├── data/                      # Local DATA_DIR (cookies + chartink.db) — do not commit secrets
├── requirements.txt
├── Dockerfile
└── .env.example
```

## How Chartink Access Works

Chartink has no public API. This server reverse-engineers the authenticated web flow:

1. **Login** — Playwright fills the login form at `/login` and captures session cookies
2. **CSRF** — Screener pages embed a CSRF token; requests must send matching `X-CSRF-TOKEN` / `X-XSRF-TOKEN` with cookies bound to `chartink.com`
3. **Scan execution** — POST to `/screener/process` with `scan_clause`
4. **Session reuse** — Cookies persist under `DATA_DIR` (local: `data/`, Render: often `/tmp` unless you set a disk)
5. **Auto-refresh** — `POST /refresh-session` (may hit CAPTCHA on some IPs)

Run `scripts/inspect_chartink.py` to discover endpoints and scan metadata for your account.

## Security Notes

- Never commit `.env` with real credentials
- Use Render secret environment variables
- Set `WEBHOOK_SECRET` for webhook authentication
- Chartink may show CAPTCHA on login — prefer persisted cookies or local login first

## License

MIT
