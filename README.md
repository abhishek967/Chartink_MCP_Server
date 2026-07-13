# Chartink Intelligence MCP

A production server that connects **Claude / ChatGPT** to your **Chartink** account, and also builds a **daily historical market database** so the project can grow into a long-term stock research platform.

**Live app:** [https://chartink-mcp-server-2.onrender.com](https://chartink-mcp-server-2.onrender.com)  
**MCP URL:** `https://chartink-mcp-server-2.onrender.com/mcp` (Streamable HTTP — **no OAuth**)

Application code lives in the **`chartink-mcp/`** directory. This is the **only** project README.

---

## What this project is

Chartink has **no official public API**. This codebase reverse-engineers Chartink’s authenticated website (login cookies, screeners, Atlas widgets) and exposes that power in three ways:

| Surface | Who uses it | Purpose |
|---------|-------------|---------|
| **MCP** (`/mcp`) | Claude Desktop / ChatGPT | Ask natural-language questions; the AI calls tools |
| **REST** (`/health`, `/atlas`, `/scans`, …) | Scripts, Postman, curl | Direct HTTP access without MCP |
| **Collector** (CLI + Cron) | Automation | Every trading day, run configured scans and store scores in SQLite |

**Important rule:** the daily collector does **not** go through MCP. Business logic lives in **services**; MCP tools and the Cron/CLI are thin callers. Existing Claude tooling must stay intact as we add history.

---

## What we have built so far

### 1. Core MCP + Chartink bridge (production)

- FastAPI web app + FastMCP server in one process
- Playwright-based Chartink login, cookie persistence, session refresh
- Screener scan execution (`/screener/process`) with CSRF-safe cookies
- Atlas dashboards (e.g. **5IvaWealth Advanced**) — run widgets, merge stocks, high conviction
- Alerts / watchlists sync
- Cross-scan analysis tools (conviction, breakouts, swing watchlists, etc.)
- Deployed on **Render** with health checks and Streamable HTTP MCP

### 2. Phase 1 — Daily market collector (manual / CLI)

- Configurable scan list (`COLLECTION_SCAN_NAMES`)
- Optional friendly-name → screener slug map (`COLLECTION_SCAN_SLUGS`)
- Provider abstraction (Chartink now, MarketSmith stub later)
- Score engine → `final_score` + breakdown
- SQLite tables: `collection_runs`, `market_signals`
- Duplicate prevention via `--idempotent-date`
- Independently verified locally (example: **4/4 scans**, **783** signals stored)

### 3. Phase 2 — Render Cron wiring

- Cron cannot share `/tmp` with the web service, so Cron **HTTP-triggers** the web app:
  - `POST /jobs/collect-daily` with header `X-Cron-Secret`
- Schedule in `render.yaml`: weekdays **16:00 IST** (`30 10 * * 1-5` UTC)
- Entrypoint: `scripts/trigger_collect.sh`
- Still needs dashboard secrets (`CRON_SECRET`, scan env vars) and preferably a **persistent disk** for `DATA_DIR`

### Not done yet (future)

- MarketSmith enrichment
- Historical performance / return jobs (`return_5d`, etc. columns exist, not filled yet)
- New MCP tools that *read* historical `market_signals` for “what worked over time”
- Atlas widgets that have no `/screener/...` URL (e.g. some Equimantum reports)

---

## Big-picture architecture

```text
                    ┌─────────────────────┐
                    │  Claude / ChatGPT   │
                    │  (natural language) │
                    └──────────┬──────────┘
                               │ MCP Streamable HTTP
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                     app/server.py                            │
│  FastAPI REST  +  FastMCP (/mcp)  +  combined lifespan       │
└───────────────┬──────────────────────────────┬───────────────┘
                │                              │
                ▼                              ▼
         routes/* (HTTP)                 tools/* (MCP tools)
                │                              │
                └──────────────┬───────────────┘
                               ▼
                    app/dependencies.py
                               │
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
   clients/              auth/session_manager   analysis/
   chartink + atlas      (+ Playwright login)   market_analysis
         │                     │
         └──────────┬──────────┘
                    ▼
              storage/ (SQLite chartink.db)


   Cron / CLI path (does not use MCP tools):

   scripts/trigger_collect.sh  ──POST──►  routes/jobs.py
   jobs/daily_collector.py     ─────────►  services/collection_service.py
                                                  │
                                    providers/ + score_engine
                                                  │
                                            storage/repository
```

---

## Components — what each folder/file is for

### `app/` — process wiring

| File | Role |
|------|------|
| `server.py` | Main entry. Creates FastAPI + FastMCP, merges lifespans, mounts `/mcp`, registers routers |
| `config.py` | Loads `.env` / Render env: credentials, `DATA_DIR`, collector scan names/slugs, secrets |
| `dependencies.py` | Shared factories: session manager, Chartink/Atlas clients, repository, analysis service |
| `exception_handlers.py` | Maps auth/client errors to HTTP status codes (e.g. 401 instead of 500) |

### `auth/` — Chartink login & cookies

| File | Role |
|------|------|
| `session_manager.py` | Loads/saves cookies, validates session, refreshes login, builds HTTP clients with cookies bound to `chartink.com` (avoids CSRF mismatches) |
| `browser_login.py` | Sync Playwright login helper |
| `browser_login_worker.py` | Login runs in a **subprocess** so Playwright never blocks FastAPI’s asyncio loop |

### `clients/` — talk to Chartink’s website

| File | Role |
|------|------|
| `chartink_client.py` | Screeners: discover/resolve scans, extract `scan_clause`, POST `/screener/process`, profile/alerts/watchlists |
| `atlas_client.py` | Atlas dashboards: list dashboards, widgets, `/widget/process`, merge symbols, high conviction |

### `tools/` — MCP tools Claude/ChatGPT can call

| File | Role |
|------|------|
| `scans.py` | `run_scan`, `get_all_scans`, conviction/breakout/swing helpers over scan data |
| `atlas.py` | Atlas dashboard tools (`get_atlas_*`, `run_atlas_dashboard`, …) |
| `analytics.py` | Extra analytics tools (stock details, sector leaders, …) |
| `alerts.py` / `watchlists.py` | Alert and watchlist MCP tools |

These register onto the FastMCP instance. They call clients/analysis — **not** the collector.

### `routes/` — plain HTTP REST

| File | Role |
|------|------|
| `health.py` | `/`, `/health`, `/health/detail`, `/scans`, `/alerts`, `/watchlists`, `/refresh-session` |
| `atlas.py` | `/atlas/dashboards/...` REST mirror of Atlas features |
| `webhook.py` | `POST /webhook/chartink` for Chartink alert webhooks |
| `jobs.py` | `POST /jobs/collect-daily` — **Phase 2** Cron trigger (secret-protected); runs `CollectionService` on the web instance |

### `analysis/` — cross-scan intelligence (live MCP)

| File | Role |
|------|------|
| `market_analysis.py` | Common stocks, conviction ranking, market summary, breakout report, swing watchlist — used by MCP analytics tools |

### `providers/` + `services/` + `jobs/` — historical collector (Phase 1+)

| File | Role |
|------|------|
| `providers/base.py` | Provider-agnostic types: scan rows, observations, provider protocol |
| `providers/chartink_provider.py` | Adapts `ChartinkClient.run_scan` into normalized rows |
| `providers/marketsmith_provider.py` | Stub for a future MarketSmith data source |
| `services/score_engine.py` | Turns multi-scan observations into `final_score` + breakdown |
| `services/collection_service.py` | Orchestrates a full collection: run scans → merge → score → save |
| `jobs/daily_collector.py` | **CLI** entry (`python jobs/daily_collector.py`) — no FastMCP import |

### `storage/` — SQLite persistence

| File | Role |
|------|------|
| `database.py` | Engine + session factory; creates tables |
| `models.py` | SQLAlchemy models: users, sessions, scans, results, alerts, watchlists, analysis cache, **`CollectionRun`**, **`MarketSignal`** |
| `repository.py` | All DB reads/writes (upsert scans, save results, collection runs, market signals, dedupe) |

**Where the DB lives:** `DATA_DIR/chartink.db`  
- Local default: `chartink-mcp/data/chartink.db`  
- Render default in blueprint: `/tmp/chartink.db` (ephemeral — use a persistent disk in production)

### `scripts/` — ops & tests

| Script | Role |
|--------|------|
| `setup.sh` | Create venv and install deps |
| `render_build.sh` | Render build: `pip install` + Playwright Chromium |
| `trigger_collect.sh` | Phase 2 Cron: curl `POST /jobs/collect-daily` |
| `login_test.py` | Verify Chartink login |
| `scan_test.py` | Scan discovery + one execution |
| `atlas_test.py` | Atlas dashboard smoke test |
| `inspect_chartink.py` | Discover Chartink HTML/endpoints |
| `test_phase1_collector.py` | Offline Phase 1 unit checks (score, merge, dedupe, schema) |

### Config / deploy files

| File | Role |
|------|------|
| `.env` / `.env.example` | Local secrets and collector config (never commit real passwords) |
| `render.yaml` | Render Blueprint: web service + daily Cron job |
| `requirements.txt` | Python dependencies |
| `Dockerfile` / `docker-compose.yml` | Container runs (optional; Render can also use native Python) |

---

## Data model (what gets stored)

### Long-standing MCP tables

- `users`, `sessions` — account + cookie/session metadata  
- `scans`, `scan_results`, `historical_results` — screener catalog and executions  
- `alerts`, `watchlists` — synced Chartink lists  
- `analysis_cache` — cached analysis payloads  

### Phase 1 collector tables

- **`collection_runs`** — one job execution (`run_uuid`, `collection_date`, status, scan success/fail counts, `stocks_saved`)
- **`market_signals`** — one row per symbol per run (`triggered_scans`, `scan_count`, `final_score`, `score_breakdown`, optional future MarketSmith / return columns)

Live MCP `run_scan` tools do **not** write `market_signals`. Only the collector path does.

---

## Request flows (how pieces connect)

### A. Claude asks about Atlas stocks

```text
Claude → MCP tool get_atlas_high_conviction_stocks
      → tools/atlas.py
      → AtlasClient (auth cookies)
      → Chartink /widget/process
      → JSON back to Claude
```

### B. Claude asks to run a named screener

```text
Claude → MCP tool run_scan("Trend Template")
      → ChartinkClient.resolve + /screener/process
      → optional save to scans/scan_results
      → JSON back to Claude
```

### C. Daily historical collection (Phase 1 / 2)

```text
CLI or Cron → CollectionService
           → ChartinkProvider.run_scan for each COLLECTION_SCAN_NAMES entry
           → merge symbols across scans
           → score_engine.calculate_stock_score
           → repository → collection_runs + market_signals
```

Cron path specifically:

```text
Render Cron → scripts/trigger_collect.sh
           → POST /jobs/collect-daily (X-Cron-Secret)
           → same CollectionService on the web box (shared SQLite)
```

---

## Environment variables (what they control)

| Variable | Used by | Purpose |
|----------|---------|---------|
| `CHARTINK_EMAIL` / `CHARTINK_PASSWORD` | Auth | Automated login |
| `DATA_DIR` | Config / storage | Cookies + `chartink.db` root |
| `PLAYWRIGHT_BROWSERS_PATH` | Auth / build | Where Chromium lives on Render |
| `CHARTINK_AUTO_LOGIN` | Auth | Allow automated re-login |
| `ATLAS_DEFAULT_DASHBOARD` | Atlas tools | Default dashboard name |
| `COLLECTION_SCAN_NAMES` | Collector | Comma-separated scan names to run daily |
| `COLLECTION_SCAN_SLUGS` | Collector | `Name:slug` pairs so friendly names resolve |
| `COLLECTION_SCAN_DELAY_SECONDS` | Collector | Pause between scans |
| `CRON_SECRET` / `WEBHOOK_SECRET` | Jobs / webhook | Protect `POST /jobs/collect-daily` and webhooks |

---

## Status checklist

| Area | Status |
|------|--------|
| MCP + Atlas on Render | Live |
| Phase 1 collector code + schema | On `main`; verified locally |
| Phase 2 Cron endpoint + blueprint | On `main` (`POST /jobs/collect-daily` live) |
| Enable Cron job + `CRON_SECRET` in Render dashboard | Operator step |
| Persistent disk for history | Recommended |
| MarketSmith / returns / history MCP tools | Future |

---

## Phase 1 — run the collector manually

```bash
cd chartink-mcp
cp .env.example .env   # set email/password, DATA_DIR=data, COLLECTION_SCAN_* 

.venv/bin/python jobs/daily_collector.py
.venv/bin/python jobs/daily_collector.py --idempotent-date
.venv/bin/python scripts/test_phase1_collector.py
```

Inspect DB:

```bash
sqlite3 data/chartink.db
.tables
SELECT COUNT(*) FROM market_signals;
SELECT symbol, final_score, scan_count FROM market_signals ORDER BY final_score DESC LIMIT 10;
```

Scan names must resolve to Chartink **screener** pages (or `scans` table / `COLLECTION_SCAN_SLUGS`). Atlas-only widgets without a screener URL will not collect yet.

---

## Phase 2 — Render Cron

Schedule: Mon–Fri **16:00 IST** (`30 10 * * 1-5` UTC) via `chartink-daily-collector` in `render.yaml`.

```bash
# After CRON_SECRET is set on Render:
curl -sS -X POST \
  -H "X-Cron-Secret: $CRON_SECRET" \
  "https://chartink-mcp-server-2.onrender.com/jobs/collect-daily?idempotent=true"
```

Dashboard steps:

1. Set `CRON_SECRET`, `COLLECTION_SCAN_NAMES`, `COLLECTION_SCAN_SLUGS` on the **web** service  
2. Prefer persistent `DATA_DIR` (not only `/tmp`)  
3. Create/sync the Cron job with the same `CRON_SECRET` and start command `bash scripts/trigger_collect.sh`

---

## Quick start (local server)

```bash
cd chartink-mcp
./setup.sh
cp .env.example .env   # fill CHARTINK_* and DATA_DIR=data

.venv/bin/python scripts/login_test.py
.venv/bin/uvicorn app.server:app --reload --host 0.0.0.0 --port 8000
```

- Health: `http://localhost:8000/health`  
- Docs: `http://localhost:8000/docs`  
- MCP: `http://localhost:8000/mcp`

### Docker

```bash
docker-compose up --build
```

---

## HTTP endpoints (REST)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service identity |
| GET | `/health` | Liveness |
| GET | `/health/detail` | Auth + storage diagnostics |
| GET | `/scans` | List/sync scans |
| GET | `/alerts` | List alerts |
| GET | `/watchlists` | List watchlists |
| POST | `/refresh-session` | Force Chartink login refresh |
| GET/POST | `/atlas/dashboards/...` | Atlas REST |
| POST | `/webhook/chartink` | Inbound Chartink alerts |
| POST | `/jobs/collect-daily` | Cron/manual collect (secret required) |
| MCP | `/mcp` | Streamable HTTP MCP |

---

## MCP tools (Claude / ChatGPT)

### Scans & analysis

| Tool | Description |
|------|-------------|
| `health_check` | Server + session health |
| `get_profile` | Chartink profile |
| `get_all_scans` / `search_scans` | Scan catalog |
| `run_scan` / `get_scan_results` | Execute / read scan |
| `find_common_stocks` | Multi-scan overlap |
| `rank_high_conviction_stocks` | Conviction ranking |
| `generate_market_summary` | Aggregate summary |
| `generate_breakout_report` | Breakout analysis |
| `generate_swing_watchlist` | Swing candidates |
| `get_top_momentum_stocks` | Momentum list |
| `find_sector_leaders` | Sector leaders |
| `calculate_conviction_score` | Score one symbol |
| `get_stock_details` | Symbol details |
| `get_alerts` / `get_watchlists` | Synced lists |

### Atlas

| Tool | Description |
|------|-------------|
| `get_atlas_dashboards` | List dashboards |
| `get_atlas_dashboard_widgets` | Widget metadata |
| `run_atlas_dashboard` | Run all widgets |
| `get_atlas_dashboard_stocks` | Merged symbols |
| `get_atlas_high_conviction_stocks` | Multi-widget hits |

### MCP resources

- `chartink://scans`, `chartink://results`, `chartink://history`, `chartink://watchlists`, `chartink://alerts`

---

## Connect Claude / ChatGPT

```text
https://chartink-mcp-server-2.onrender.com/mcp
```

- **No OAuth Client ID** — Chartink login is server-side via env credentials  
- Claude Desktop example:

```json
{
  "mcpServers": {
    "chartink": {
      "type": "http",
      "url": "https://chartink-mcp-server-2.onrender.com/mcp"
    }
  }
}
```

---

## Deploy notes (Render)

Current production style: **native Python** + `scripts/render_build.sh` (installs Playwright Chromium into `.playwright-browsers`).

Required secrets: `CHARTINK_EMAIL`, `CHARTINK_PASSWORD`.  
For Phase 2 also: `CRON_SECRET`, `COLLECTION_SCAN_NAMES`, optional `COLLECTION_SCAN_SLUGS`.

**Session tip:** Chartink may show CAPTCHA on automated login. Prefer a warm `cookies.json` under `DATA_DIR`, or `POST /refresh-session` when needed.

---

## How Chartink access works (technical)

1. **Login** — Playwright submits `/login`, captures `ci_session` / `XSRF-TOKEN` / remember cookie  
2. **CSRF** — Screener pages expose a meta CSRF token; POSTs send `X-CSRF-TOKEN` + `X-XSRF-TOKEN` with domain-scoped cookies  
3. **Scan run** — GET screener HTML → extract `scan_clause` → POST `/screener/process`  
4. **Atlas run** — resolve dashboard → each widget `/widget/process` → merge symbols  
5. **Persistence** — cookies + SQLite under `DATA_DIR`

---

## Security

- Never commit real `.env` credentials  
- Store secrets in Render’s encrypted env  
- Protect Cron/webhooks with `CRON_SECRET` / `WEBHOOK_SECRET`  
- Treat Chartink CAPTCHA as an operational constraint, not a code bug alone  

---

## License

MIT
