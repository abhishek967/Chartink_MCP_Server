"""Atlas dashboard REST endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.dependencies import AtlasClientDep

router = APIRouter(prefix="/atlas", tags=["atlas"])


@router.get("/dashboards")
def list_atlas_dashboards(client: AtlasClientDep) -> list[dict[str, Any]]:
    return client.get_user_dashboards()


@router.get("/dashboards/{dashboard_name_or_id}/widgets")
def get_dashboard_widgets(
    dashboard_name_or_id: str,
    client: AtlasClientDep,
) -> dict[str, Any]:
    return client.get_dashboard_widgets(dashboard_name_or_id)


@router.post("/dashboards/{dashboard_name_or_id}/run")
def run_dashboard(
    dashboard_name_or_id: str,
    client: AtlasClientDep,
) -> dict[str, Any]:
    result = client.run_dashboard(dashboard_name_or_id, cache=True)
    for widget in result.get("widgets", []):
        widget.pop("raw", None)
    return result


@router.get("/dashboards/{dashboard_name_or_id}/stocks")
def get_dashboard_stocks(
    dashboard_name_or_id: str,
    client: AtlasClientDep,
    use_cache: bool = Query(default=True),
) -> dict[str, Any]:
    return client.get_dashboard_stocks(dashboard_name_or_id, use_cache=use_cache)
