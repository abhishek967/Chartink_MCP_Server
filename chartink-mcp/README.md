# Chartink Intelligence MCP

Production-grade MCP server that gives ChatGPT (and other MCP clients) authenticated access to your Chartink account — scans, alerts, watchlists, and cross-scan market analysis.

## Architecture

```
Chartink Client Layer
        ↓
Session Manager (Playwright login + cookie persistence)
        ↓
Storage Layer (SQLite + repository pattern)
        ↓
Analysis Layer (conviction scoring, sector leaders)
        ↓
MCP Server (FastMCP) + FastAPI REST
        ↓
ChatGPT / MCP Clients
```

## Features

- Browser-based Chartink login with persistent `ci_session` cookies
- Automatic session validation and re-authentication
- Scan discovery, execution, and historical result storage
- Alerts and watchlist sync
- Cross-scan conviction scoring and market summaries
- MCP tools + resources for ChatGPT integration
- FastAPI REST endpoints for health, scans, and webhooks
- Docker-ready for Render/Railway deployment

## Quick Start

### 1. Configure environment

```bash
cd chartink-mcp
cp .env.example .env
# Edit .env with your CHARTINK_EMAIL and CHARTINK_PASSWORD
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
│   ├── server.py          # FastAPI + FastMCP entrypoint
│   ├── config.py          # Settings from .env
│   └── dependencies.py    # DI container
├── clients/
│   └── chartink_client.py # Reverse-engineered HTTP client
├── auth/
│   └── session_manager.py # Playwright login + cookies
├── storage/
│   ├── database.py
│   ├── models.py
│   └── repository.py
├── analysis/
│   └── market_analysis.py
├── tools/
│   ├── scans.py
│   ├── watchlists.py
│   ├── alerts.py
│   └── analytics.py
├── routes/
│   ├── health.py
│   └── webhook.py
├── scripts/
│   ├── inspect_chartink.py
│   ├── login_test.py
│   └── scan_test.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## How Chartink Access Works

Chartink has no public API. This server reverse-engineers the authenticated web flow:

1. **Login** — Playwright fills the login form at `/login` and captures session cookies
2. **CSRF** — Each screener page embeds a CSRF token in a `<meta>` tag
3. **Scan execution** — POST to `/screener/process` with `scan_clause` payload
4. **Session reuse** — Cookies persist in `data/cookies.json` and SQLite between restarts
5. **Auto-refresh** — On-demand via `POST /refresh-session` (startup auto-login is off by default)

Run `scripts/inspect_chartink.py` to discover endpoints and scan metadata for your account.

## Security Notes

- Never commit `.env` with real credentials
- Use Render/Railway secret environment variables
- Set `WEBHOOK_SECRET` for webhook authentication
- Chartink may show CAPTCHA on login — run inspection locally first if needed

## License

MIT
