"""MCP tools for Chartink Atlas dashboards."""

from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP

from app.config import get_settings
from app.dependencies import get_atlas_client


def register_atlas_tools(mcp: FastMCP) -> None:
    settings = get_settings()
    atlas = get_atlas_client()
    default_dashboard = settings.atlas_default_dashboard

    @mcp.tool()
    def get_atlas_dashboards() -> list[dict[str, Any]]:
        """List all Atlas dashboards available to your Chartink account."""
        dashboards = atlas.get_user_dashboards()
        return [
            {
                "id": d.get("id"),
                "name": d.get("name"),
                "widget_count": d.get("widgetCount"),
                "is_private": d.get("is_private"),
                "updated_at": d.get("updated_at"),
            }
            for d in dashboards
        ]

    @mcp.tool()
    def get_atlas_dashboard_widgets(
        dashboard_name_or_id: str = default_dashboard,
    ) -> dict[str, Any]:
        """Get widgets configured on an Atlas dashboard."""
        payload = atlas.get_dashboard_widgets(dashboard_name_or_id)
        widgets = payload.get("widgets", [])
        return {
            "dashboard": payload.get("dashboard"),
            "widgets": [
                {
                    "id": w.get("id"),
                    "name": w.get("name"),
                    "description": w.get("description"),
                    "result_type": (w.get("jsondetails") or {}).get("resultType"),
                }
                for w in widgets
            ],
            "widget_count": len(widgets),
        }

    @mcp.tool()
    def run_atlas_dashboard(
        dashboard_name_or_id: str = default_dashboard,
    ) -> dict[str, Any]:
        """Execute all widgets on an Atlas dashboard and return stocks per widget."""
        result = atlas.run_dashboard(dashboard_name_or_id, cache=True)
        # Trim raw payloads for MCP response size
        for widget in result.get("widgets", []):
            widget.pop("raw", None)
        return result

    @mcp.tool()
    def get_atlas_dashboard_stocks(
        dashboard_name_or_id: str = default_dashboard,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Get merged unique stock symbols from an Atlas dashboard."""
        return atlas.get_dashboard_stocks(dashboard_name_or_id, use_cache=use_cache)

    @mcp.tool()
    def get_atlas_high_conviction_stocks(
        dashboard_name_or_id: str = default_dashboard,
        min_widget_hits: int = 2,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """Get stocks that appear in multiple widgets on the same Atlas dashboard."""
        return atlas.get_high_conviction_stocks(
            dashboard_name_or_id,
            min_widget_hits=min_widget_hits,
            use_cache=use_cache,
        )

    @mcp.resource("chartink://atlas/dashboards")
    def atlas_dashboards_resource() -> str:
        """Atlas dashboards catalog."""
        dashboards = atlas.get_user_dashboards()
        return json.dumps(dashboards, indent=2, default=str)

    @mcp.resource("chartink://atlas/stocks")
    def atlas_stocks_resource() -> str:
        """Latest merged stocks from the default Atlas dashboard."""
        stocks = atlas.get_dashboard_stocks(default_dashboard, use_cache=True)
        return json.dumps(stocks, indent=2, default=str)
