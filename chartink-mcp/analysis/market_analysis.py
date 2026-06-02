"""Market analysis engine for cross-scan intelligence."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from clients.chartink_client import ChartinkClient
from storage.repository import ChartinkRepository


class ChartinkAnalysisService:
    """Cross-scan analysis: conviction scoring, sector leaders, watchlists."""

    def __init__(
        self,
        client: ChartinkClient,
        repository: ChartinkRepository,
    ) -> None:
        self.client = client
        self.repository = repository

    def find_repeat_symbols(
        self,
        scan_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, int]:
        """Count how many scans each symbol appears in."""
        if scan_results is None:
            scan_results = self._collect_all_scan_results()
        symbol_counts: Counter[str] = Counter()
        for batch in scan_results:
            for row in batch.get("results", []):
                symbol = self._symbol_key(row)
                if symbol:
                    symbol_counts[symbol] += 1
        return dict(symbol_counts.most_common())

    def calculate_conviction_score(
        self,
        symbol: str,
        scan_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Score conviction based on multi-scan presence and momentum."""
        repeats = self.find_repeat_symbols(scan_results)
        count = repeats.get(symbol.upper(), 0)
        max_count = max(repeats.values()) if repeats else 1
        base_score = (count / max_count) * 100 if max_count else 0

        momentum_bonus = 0.0
        avg_per_chg = 0.0
        per_chg_values: list[float] = []
        if scan_results is None:
            scan_results = self._collect_all_scan_results()
        for batch in scan_results:
            for row in batch.get("results", []):
                if self._symbol_key(row) == symbol.upper():
                    try:
                        per_chg_values.append(float(row.get("per_chg", 0)))
                    except (TypeError, ValueError):
                        pass
        if per_chg_values:
            avg_per_chg = sum(per_chg_values) / len(per_chg_values)
            if avg_per_chg > 3:
                momentum_bonus = min(20, avg_per_chg)
            elif avg_per_chg > 1:
                momentum_bonus = min(10, avg_per_chg)

        total_score = min(100, round(base_score + momentum_bonus, 2))
        return {
            "symbol": symbol.upper(),
            "scan_appearances": count,
            "conviction_score": total_score,
            "avg_per_chg": round(avg_per_chg, 2),
            "rating": self._rating_from_score(total_score),
        }

    def find_multi_scan_candidates(
        self,
        min_scans: int = 2,
    ) -> list[dict[str, Any]]:
        """Find stocks appearing in multiple scans."""
        scan_results = self._collect_all_scan_results()
        repeats = self.find_repeat_symbols(scan_results)
        candidates = []
        for symbol, count in repeats.items():
            if count >= min_scans:
                candidates.append(self.calculate_conviction_score(symbol, scan_results))
        candidates.sort(key=lambda x: x["conviction_score"], reverse=True)
        return candidates

    def find_sector_leaders(
        self,
        scan_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Group top momentum stocks by sector."""
        if scan_results is None:
            scan_results = self._collect_all_scan_results()
        sector_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
        seen: set[str] = set()
        for batch in scan_results:
            for row in batch.get("results", []):
                symbol = self._symbol_key(row)
                if not symbol or symbol in seen:
                    continue
                seen.add(symbol)
                sector = row.get("sector") or "Unknown"
                try:
                    per_chg = float(row.get("per_chg", 0))
                except (TypeError, ValueError):
                    per_chg = 0.0
                sector_map[str(sector)].append(
                    {
                        "symbol": symbol,
                        "per_chg": per_chg,
                        "close": row.get("close"),
                        "volume": row.get("volume"),
                    }
                )
        leaders: dict[str, list[dict[str, Any]]] = {}
        for sector, stocks in sector_map.items():
            leaders[sector] = sorted(stocks, key=lambda s: s["per_chg"], reverse=True)[:5]
        return leaders

    def generate_watchlist(
        self,
        min_conviction: float = 60.0,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Generate a swing watchlist from high-conviction multi-scan stocks."""
        candidates = self.find_multi_scan_candidates(min_scans=2)
        watchlist = [c for c in candidates if c["conviction_score"] >= min_conviction]
        return watchlist[:limit]

    def generate_breakout_report(
        self,
        scan_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Generate breakout analysis from scan results."""
        if scan_names:
            scan_results = []
            for name in scan_names:
                try:
                    scan_results.append(self.client.run_scan(name))
                except Exception:
                    continue
        else:
            scan_results = self._collect_all_scan_results()

        breakouts: list[dict[str, Any]] = []
        for batch in scan_results:
            scan_name = batch.get("scan_name", "Unknown")
            for row in batch.get("results", []):
                try:
                    per_chg = float(row.get("per_chg", 0))
                except (TypeError, ValueError):
                    per_chg = 0.0
                if per_chg >= 2.0:
                    breakouts.append(
                        {
                            "symbol": self._symbol_key(row),
                            "scan_name": scan_name,
                            "per_chg": per_chg,
                            "close": row.get("close"),
                            "volume": row.get("volume"),
                        }
                    )
        breakouts.sort(key=lambda x: x["per_chg"], reverse=True)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_breakouts": len(breakouts),
            "breakouts": breakouts[:50],
            "top_sectors": self._top_sectors_from_breakouts(breakouts),
        }

    def generate_market_summary(self) -> dict[str, Any]:
        """Generate an aggregate market summary from all cached/live scans."""
        cache_key = "market_summary"
        cached = self.repository.get_analysis_cache(cache_key)
        if cached:
            return cached.payload_json

        scans = self.repository.list_scans() if self.repository else []
        scan_results = self._collect_all_scan_results()
        all_stocks: list[dict[str, Any]] = []
        for batch in scan_results:
            all_stocks.extend(batch.get("results", []))

        per_chg_values: list[float] = []
        for row in all_stocks:
            try:
                per_chg_values.append(float(row.get("per_chg", 0)))
            except (TypeError, ValueError):
                pass

        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_scans_analyzed": len(scan_results),
            "total_unique_stocks": len(self.find_repeat_symbols(scan_results)),
            "avg_market_change": round(sum(per_chg_values) / len(per_chg_values), 2)
            if per_chg_values
            else 0,
            "top_momentum": self._top_momentum(all_stocks, limit=10),
            "high_conviction": self.find_multi_scan_candidates(min_scans=2)[:10],
            "sector_leaders": {
                k: v[:3] for k, v in list(self.find_sector_leaders(scan_results).items())[:5]
            },
            "scan_count": len(scans),
        }
        self.repository.set_analysis_cache(cache_key, "market_summary", summary)
        return summary

    def rank_high_conviction_stocks(self, limit: int = 25) -> list[dict[str, Any]]:
        """Rank stocks by conviction score across all scans."""
        candidates = self.find_multi_scan_candidates(min_scans=1)
        return candidates[:limit]

    def get_top_momentum_stocks(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return top momentum stocks across all scan results."""
        scan_results = self._collect_all_scan_results()
        all_stocks: list[dict[str, Any]] = []
        for batch in scan_results:
            all_stocks.extend(batch.get("results", []))
        return self._top_momentum(all_stocks, limit=limit)

    def find_common_stocks(self, min_scans: int = 2) -> list[dict[str, Any]]:
        """Alias for multi-scan candidate discovery."""
        return self.find_multi_scan_candidates(min_scans=min_scans)

    def _collect_all_scan_results(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        scans = self.repository.list_scans()
        for scan in scans:
            latest = self.repository.get_latest_scan_result(scan.id)
            if latest:
                results.append(
                    {
                        "scan_name": scan.name,
                        "results": latest.results_json,
                    }
                )
        if not results:
            live_scans = self.client.get_all_scans(sync_db=True)
            for scan in live_scans[:10]:
                try:
                    results.append(self.client.run_scan(scan["name"]))
                except Exception:
                    continue
        return results

    @staticmethod
    def _symbol_key(row: dict[str, Any]) -> str:
        return str(row.get("nsecode") or row.get("bsecode") or row.get("name", "")).upper()

    @staticmethod
    def _rating_from_score(score: float) -> str:
        if score >= 80:
            return "Very High"
        if score >= 60:
            return "High"
        if score >= 40:
            return "Medium"
        if score >= 20:
            return "Low"
        return "Very Low"

    @staticmethod
    def _top_momentum(stocks: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
        ranked: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in stocks:
            symbol = ChartinkAnalysisService._symbol_key(row)
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            try:
                per_chg = float(row.get("per_chg", 0))
            except (TypeError, ValueError):
                per_chg = 0.0
            ranked.append(
                {
                    "symbol": symbol,
                    "per_chg": per_chg,
                    "close": row.get("close"),
                    "volume": row.get("volume"),
                }
            )
        ranked.sort(key=lambda x: x["per_chg"], reverse=True)
        return ranked[:limit]

    @staticmethod
    def _top_sectors_from_breakouts(breakouts: list[dict[str, Any]]) -> list[str]:
        sectors: Counter[str] = Counter()
        for b in breakouts:
            sector = b.get("sector", "Unknown")
            sectors[str(sector)] += 1
        return [s for s, _ in sectors.most_common(5)]
