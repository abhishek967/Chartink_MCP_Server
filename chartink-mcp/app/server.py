"""Chartink Intelligence MCP — FastAPI + FastMCP server entrypoint."""

from __future__ import annotations

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

    if settings.chartink_startup_auto_login:
        if settings.chartink_email and settings.chartink_password:
            if not session_manager.validate_session():
                logger.info("No valid session found, attempting startup auto-login")
                try:
                    session_manager.auto_reauthenticate()
                except Exception as exc:
                    logger.warning(
                        "Startup auto-login failed (non-fatal, service will continue): {}",
                        exc,
                    )
            else:
                logger.info("Existing Chartink session is valid")
        else:
            logger.warning(
                "CHARTINK_EMAIL/PASSWORD not set — login required via POST /refresh-session"
            )
    else:
        session_manager.log_startup_auto_login_skipped()
        try:
            if session_manager.validate_session():
                logger.info("Loaded Chartink session cookies are valid")
            elif settings.chartink_email:
                logger.warning(
                    "Chartink session invalid or missing — authenticate via "
                    "POST /refresh-session or upload cookies to the persistent disk"
                )
        except Exception as exc:
            logger.warning(
                "Session validation failed on startup (non-fatal): {}", exc
            )
    yield
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
