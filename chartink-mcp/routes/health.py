"""Health check REST endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger

from app.config import get_settings
from auth.browser_login import is_playwright_browser_installed
from auth.session_manager import AuthenticationError
from app.dependencies import ChartinkClientDep, RepositoryDep, SessionManagerDep

router = APIRouter(tags=["health"])


@router.get("/")
def root() -> dict[str, str]:
    return {
        "status": "healthy",
        "service": "Chartink Intelligence MCP",
    }


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe for Render/Docker — does not require Chartink auth."""
    return {"status": "ok"}


@router.get("/health/detail")
def health_detail(
    client: ChartinkClientDep,
    repository: RepositoryDep,
    session_manager: SessionManagerDep,
) -> dict[str, Any]:
    settings = get_settings()
    authenticated = client.is_authenticated()
    playwright_ready = is_playwright_browser_installed()
    return {
        "status": "ok" if authenticated else "degraded",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "data_dir": str(settings.data_dir),
        "cookies_file": str(settings.cookies_file),
        "authenticated": authenticated,
        "playwright_ready": playwright_ready,
        "chartink_credentials_set": bool(
            settings.chartink_email and settings.chartink_password
        ),
        "scans_count": len(repository.list_scans()),
        "alerts_count": len(repository.list_alerts()),
        "watchlists_count": len(repository.list_watchlists()),
        "cookies_loaded": bool(session_manager.get_cookies()),
    }


@router.get("/scans")
def list_scans(client: ChartinkClientDep) -> list[dict[str, Any]]:
    return client.get_all_scans(sync_db=True)


@router.get("/alerts")
def list_alerts(client: ChartinkClientDep) -> list[dict[str, Any]]:
    return client.get_alerts(sync_db=True)


@router.get("/watchlists")
def list_watchlists(client: ChartinkClientDep) -> list[dict[str, Any]]:
    return client.get_watchlists(sync_db=True)


@router.get("/refresh-session")
def refresh_session_info() -> dict[str, str]:
    """Hint when opened in a browser — login requires POST."""
    return {
        "message": "Use POST on this URL to refresh the Chartink session.",
        "method": "POST",
        "url": "/refresh-session",
    }


@router.post("/refresh-session")
def refresh_session(session_manager: SessionManagerDep) -> dict[str, Any]:
    """Explicit browser login; may fail on Render (CAPTCHA / Playwright limits)."""
    try:
        cookies = session_manager.refresh_session()
        valid = session_manager.validate_session()
        return {
            "refreshed": True,
            "valid": valid,
            "cookie_count": len(cookies),
        }
    except AuthenticationError as exc:
        logger.warning("refresh-session failed: {}", exc)
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("refresh-session unexpected error: {}", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Session refresh failed: {exc}",
        ) from exc
