"""Health check REST endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger

from app.config import get_settings
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
    return {
        "status": "ok" if authenticated else "degraded",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "authenticated": authenticated,
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
