"""External market data provider interfaces (provider-agnostic)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ScanHitRow:
    """One stock row returned by a single scan/screener."""

    symbol: str
    company_name: str | None = None
    sector: str | None = None
    close_price: float | None = None
    per_chg: float | None = None
    volume: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScanExecutionResult:
    """Result of executing one named scan."""

    scan_name: str
    success: bool
    rows: list[ScanHitRow] = field(default_factory=list)
    error: str | None = None
    records_total: int = 0


@dataclass
class StockObservation:
    """
    Normalized multi-scan observation for scoring.

    Chartink fills technical fields today; MarketSmith may add ratings later
    without changing ScoreEngine's public API.
    """

    symbol: str
    company_name: str | None = None
    sector: str | None = None
    close_price: float | None = None
    per_chg: float | None = None
    volume: float | None = None
    triggered_scans: list[str] = field(default_factory=list)
    scan_count: int = 0
    # Future MarketSmith inputs (optional)
    rs_rating: int | None = None
    eps_rating: int | None = None
    composite_rating: int | None = None
    industry_rank: int | None = None
    accumulation_distribution: str | None = None
    pattern_type: str | None = None
    market_outlook: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


class MarketDataProvider(Protocol):
    """Provider interface for scan execution and enrichment."""

    name: str

    def ensure_authenticated(self) -> None:
        """Raise if the provider cannot authenticate."""

    def run_scan(self, scan_name: str) -> ScanExecutionResult:
        """Execute a named scan and return normalized rows."""

    def enrich_observation(self, observation: StockObservation) -> StockObservation:
        """Optionally enrich an observation (e.g. MarketSmith ratings)."""
