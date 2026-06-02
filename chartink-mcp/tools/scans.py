"""MCP tools for Chartink scan operations."""

from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP

from app.dependencies import get_analysis_service, get_chartink_client, get_repository
from auth.session_manager import AuthenticationError
from clients.chartink_client import ChartinkClientError


def register_scan_tools(mcp: FastMCP) -> None:
    client = get_chartink_client()
    repository = get_repository()
    analysis = get_analysis_service()

    @mcp.tool()
    def health_check() -> dict[str, Any]:
        """Check server and Chartink session health."""
        authenticated = False
        auth_error: str | None = None
        try:
            authenticated = client.is_authenticated()
        except Exception as exc:
            auth_error = str(exc)
        return {
            "status": "healthy" if authenticated else "degraded",
            "authenticated": authenticated,
            "auth_error": auth_error,
            "scans_in_db": len(repository.list_scans()),
        }

    @mcp.tool()
    def get_profile() -> dict[str, Any]:
        """Get the authenticated Chartink user profile."""
        try:
            return client.get_profile()
        except (AuthenticationError, ChartinkClientError) as exc:
            return {"error": str(exc), "authenticated": False}

    @mcp.tool()
    def get_all_scans() -> list[dict[str, Any]]:
        """Retrieve all scans available to the authenticated account."""
        return client.get_all_scans(sync_db=True)

    @mcp.tool()
    def search_scans(keyword: str) -> list[dict[str, Any]]:
        """Search scans by keyword in name or slug."""
        return client.search_scans(keyword)

    @mcp.tool()
    def run_scan(scan_name: str) -> dict[str, Any]:
        """Execute a Chartink scan by name and return results."""
        return client.run_scan(scan_name)

    @mcp.tool()
    def get_scan_results(scan_name: str) -> dict[str, Any]:
        """Get latest scan results (cached or live)."""
        return client.get_scan_results(scan_name)

    @mcp.tool()
    def find_common_stocks(min_scans: int = 2) -> list[dict[str, Any]]:
        """Find stocks appearing in multiple scans."""
        return analysis.find_common_stocks(min_scans=min_scans)

    @mcp.tool()
    def rank_high_conviction_stocks(limit: int = 25) -> list[dict[str, Any]]:
        """Rank stocks by cross-scan conviction score."""
        return analysis.rank_high_conviction_stocks(limit=limit)

    @mcp.tool()
    def generate_market_summary() -> dict[str, Any]:
        """Generate aggregate market summary from all scans."""
        return analysis.generate_market_summary()

    @mcp.tool()
    def generate_breakout_report(scan_names: list[str] | None = None) -> dict[str, Any]:
        """Generate breakout analysis report from scan results."""
        return analysis.generate_breakout_report(scan_names=scan_names)

    @mcp.tool()
    def generate_swing_watchlist(min_conviction: float = 60.0, limit: int = 20) -> list[dict[str, Any]]:
        """Generate a swing trading watchlist from high-conviction stocks."""
        return analysis.generate_watchlist(min_conviction=min_conviction, limit=limit)

    @mcp.tool()
    def get_top_momentum_stocks(limit: int = 20) -> list[dict[str, Any]]:
        """Get top momentum stocks across all scan results."""
        return analysis.get_top_momentum_stocks(limit=limit)

    @mcp.resource("chartink://scans")
    def scans_resource() -> str:
        """List all synced scans."""
        scans = repository.list_scans()
        payload = [
            {
                "name": s.name,
                "slug": s.slug,
                "url": s.url,
                "last_synced_at": s.last_synced_at.isoformat() if s.last_synced_at else None,
            }
            for s in scans
        ]
        return json.dumps(payload, indent=2)

    @mcp.resource("chartink://results")
    def results_resource() -> str:
        """Latest scan results across all scans."""
        results = []
        for scan in repository.list_scans():
            latest = repository.get_latest_scan_result(scan.id)
            if latest:
                results.append(
                    {
                        "scan_name": scan.name,
                        "records_total": latest.records_total,
                        "executed_at": latest.executed_at.isoformat(),
                        "results": latest.results_json[:50],
                    }
                )
        return json.dumps(results, indent=2)

    @mcp.resource("chartink://history")
    def history_resource() -> str:
        """Historical scan execution records."""
        historical = repository.get_historical_results(limit=500)
        payload = [
            {
                "symbol": h.symbol,
                "scan_id": h.scan_id,
                "close": h.close,
                "per_chg": h.per_chg,
                "captured_at": h.captured_at.isoformat(),
            }
            for h in historical
        ]
        return json.dumps(payload, indent=2)
