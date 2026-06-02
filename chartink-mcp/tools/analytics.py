"""MCP tools for advanced analytics."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from app.dependencies import get_analysis_service, get_chartink_client


def register_analytics_tools(mcp: FastMCP) -> None:
    client = get_chartink_client()
    analysis = get_analysis_service()

    @mcp.tool()
    def get_stock_details(symbol: str) -> dict[str, Any]:
        """Get detailed information for a stock symbol."""
        return client.get_stock_details(symbol)

    @mcp.tool()
    def find_sector_leaders() -> dict[str, list[dict[str, Any]]]:
        """Find top momentum stocks grouped by sector."""
        return analysis.find_sector_leaders()

    @mcp.tool()
    def calculate_conviction_score(symbol: str) -> dict[str, Any]:
        """Calculate conviction score for a specific symbol."""
        return analysis.calculate_conviction_score(symbol)

    @mcp.tool()
    def find_multi_scan_candidates(min_scans: int = 2) -> list[dict[str, Any]]:
        """Find stocks appearing in multiple scans with conviction scores."""
        return analysis.find_multi_scan_candidates(min_scans=min_scans)
