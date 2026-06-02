"""MCP tools for Chartink watchlist operations."""

from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP

from app.dependencies import get_chartink_client, get_repository


def register_watchlist_tools(mcp: FastMCP) -> None:
    client = get_chartink_client()
    repository = get_repository()

    @mcp.tool()
    def get_watchlists() -> list[dict[str, Any]]:
        """Retrieve all watchlists from the Chartink account."""
        return client.get_watchlists(sync_db=True)

    @mcp.resource("chartink://watchlists")
    def watchlists_resource() -> str:
        """All synced watchlists."""
        watchlists = repository.list_watchlists()
        payload = [
            {
                "name": w.name,
                "symbols": w.symbols_json,
                "synced_at": w.synced_at.isoformat() if w.synced_at else None,
            }
            for w in watchlists
        ]
        return json.dumps(payload, indent=2)
