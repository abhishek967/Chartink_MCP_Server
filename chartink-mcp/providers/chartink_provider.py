"""Chartink market data provider — wraps ChartinkClient."""

from __future__ import annotations

from typing import Any

from loguru import logger

from clients.chartink_client import ChartinkClient, ChartinkClientError
from providers.base import ScanExecutionResult, ScanHitRow, StockObservation


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _symbol_from_row(row: dict[str, Any]) -> str:
    raw = row.get("nsecode") or row.get("bsecode") or row.get("name") or ""
    return str(raw).upper().strip()


class ChartinkProvider:
    """Adapts ChartinkClient to the MarketDataProvider interface."""

    name = "chartink"

    def __init__(self, client: ChartinkClient) -> None:
        self._client = client

    def ensure_authenticated(self) -> None:
        self._client._ensure_authenticated()

    def run_scan(self, scan_name: str) -> ScanExecutionResult:
        try:
            payload = self._client.run_scan(scan_name)
            rows_raw = payload.get("results") or []
            rows: list[ScanHitRow] = []
            for row in rows_raw:
                symbol = _symbol_from_row(row)
                if not symbol:
                    continue
                rows.append(
                    ScanHitRow(
                        symbol=symbol,
                        company_name=str(row.get("name") or "") or None,
                        sector=row.get("sector"),
                        close_price=_safe_float(row.get("close")),
                        per_chg=_safe_float(row.get("per_chg")),
                        volume=_safe_float(row.get("volume")),
                        raw=row,
                    )
                )
            return ScanExecutionResult(
                scan_name=scan_name,
                success=True,
                rows=rows,
                records_total=int(payload.get("records_total") or len(rows)),
            )
        except (ChartinkClientError, Exception) as exc:
            logger.error("Chartink scan '{}' failed: {}", scan_name, exc)
            return ScanExecutionResult(
                scan_name=scan_name,
                success=False,
                error=str(exc),
            )

    def enrich_observation(self, observation: StockObservation) -> StockObservation:
        """Chartink has no extra enrichment beyond scan rows."""
        return observation
