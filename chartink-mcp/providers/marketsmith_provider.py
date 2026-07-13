"""MarketSmith provider stub — future integration point."""

from __future__ import annotations

from providers.base import ScanExecutionResult, StockObservation


class MarketSmithProvider:
    """
    Future MarketSmith adapter.

    Does not execute scans today. ``enrich_observation`` is the extension point
    for RS/EPS/composite ratings once an API/client is available.
    """

    name = "marketsmith"

    def ensure_authenticated(self) -> None:
        return None

    def run_scan(self, scan_name: str) -> ScanExecutionResult:
        return ScanExecutionResult(
            scan_name=scan_name,
            success=False,
            error="MarketSmith provider is not configured",
        )

    def enrich_observation(self, observation: StockObservation) -> StockObservation:
        """No-op until MarketSmith credentials/client are wired."""
        return observation
