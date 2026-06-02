"""MCP tools for Chartink alert operations."""

from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP

from app.dependencies import get_chartink_client, get_repository


def register_alert_tools(mcp: FastMCP) -> None:
    client = get_chartink_client()
    repository = get_repository()

    @mcp.tool()
    def get_alerts() -> list[dict[str, Any]]:
        """Retrieve all alerts configured on the Chartink account."""
        return client.get_alerts(sync_db=True)

    @mcp.resource("chartink://alerts")
    def alerts_resource() -> str:
        """All synced alerts."""
        alerts = repository.list_alerts()
        payload = [
            {
                "name": a.name,
                "scan_name": a.scan_name,
                "scan_slug": a.scan_slug,
                "is_active": a.is_active,
                "webhook_url": a.webhook_url,
            }
            for a in alerts
        ]
        return json.dumps(payload, indent=2)
