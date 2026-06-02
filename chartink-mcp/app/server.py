"""Chartink Intelligence MCP — FastAPI + FastMCP server entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.dependencies import get_session_manager  # noqa: E402
from app.exception_handlers import register_exception_handlers  # noqa: E402
from routes.atlas import router as atlas_router  # noqa: E402
from routes.health import router as health_router  # noqa: E402
from routes.webhook import router as webhook_router  # noqa: E402
from storage.database import init_db  # noqa: E402
from tools.alerts import register_alert_tools  # noqa: E402
from tools.analytics import register_analytics_tools  # noqa: E402
from tools.atlas import register_atlas_tools  # noqa: E402
from tools.scans import register_scan_tools  # noqa: E402
from tools.watchlists import register_watchlist_tools  # noqa: E402


def configure_logging() -> None:
    settings = get_settings()
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
            "<level>{message}</level>"
        ),
    )


def create_mcp() -> FastMCP:
    settings = get_settings()
    mcp = FastMCP(
        name=settings.app_name,
        instructions=(
            "Chartink Intelligence MCP provides authenticated access to Chartink "
            "Atlas dashboards, scans, alerts, watchlists, and cross-scan market analysis "
            "for Indian equities. Use Atlas tools to run dashboards like '5IvaWealth Advanced' "
            "and retrieve merged stock lists."
        ),
    )
    register_scan_tools(mcp)
    register_watchlist_tools(mcp)
    register_alert_tools(mcp)
    register_analytics_tools(mcp)
    register_atlas_tools(mcp)
    return mcp


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    logger.info("Starting {} v{}", settings.app_name, settings.app_version)
    init_db()
    session_manager = get_session_manager()
    session_manager.load_cookies()

    refresh_task: asyncio.Task | None = None
    if settings.chartink_auto_login and settings.session_refresh_interval_minutes > 0:

        async def _periodic_session_refresh() -> None:
            interval = settings.session_refresh_interval_minutes * 60
            while True:
                await asyncio.sleep(interval)
                try:
                    await asyncio.to_thread(session_manager.refresh_session)
                except Exception as exc:
                    logger.warning("Background session refresh failed: {}", exc)

        refresh_task = asyncio.create_task(_periodic_session_refresh())

    try:
        await asyncio.to_thread(session_manager.try_startup_login)
    except Exception as exc:
        logger.warning("Startup session setup failed (non-fatal): {}", exc)

    yield
    if refresh_task is not None:
        refresh_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await refresh_task
    logger.info("Shutting down {}", settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Production MCP server for Chartink scan intelligence",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(atlas_router)
    app.include_router(webhook_router)
    return app


app = create_app()
mcp = create_mcp()
# Use SSE transport so MCP clients that expect `/sse` and `/messages/`
# receive valid endpoints under our `/mcp` mount.
mcp_app = mcp.http_app(transport="sse")
app.mount("/mcp", mcp_app)


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.server:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
