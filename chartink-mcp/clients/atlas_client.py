"""Chartink Atlas dashboard client — widgets and stock extraction."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from app.config import get_settings
from auth.session_manager import SessionManager
from storage.repository import ChartinkRepository


class AtlasClientError(Exception):
    """Raised when an Atlas operation fails."""


class AtlasClient:
    """Fetch and execute Chartink Atlas dashboards via authenticated HTTP APIs."""

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        repository: ChartinkRepository | None = None,
    ) -> None:
        self.settings = get_settings()
        self.session_manager = session_manager or SessionManager(repository=repository)
        self.repository = repository

    @property
    def base_url(self) -> str:
        return self.settings.chartink_base_url.rstrip("/")

    def _ensure_authenticated(self) -> None:
        """Require a valid session; runs automated login when CHARTINK_AUTO_LOGIN is enabled."""
        self.session_manager.ensure_authenticated()

    def _http_client(self) -> httpx.Client:
        return httpx.Client(
            cookies=self.session_manager.get_cookies(),
            timeout=self.settings.request_timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            },
        )

    def _api_headers(self, client: httpx.Client) -> dict[str, str]:
        page = client.get(f"{self.base_url}/atlas")
        soup = BeautifulSoup(page.text, "html.parser")
        meta = soup.find("meta", attrs={"name": "csrf-token"})
        csrf = str(meta["content"]) if meta and meta.get("content") else ""
        xsrf = self.session_manager.get_cookies().get("XSRF-TOKEN", "")
        return {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRF-TOKEN": csrf,
            "X-XSRF-TOKEN": xsrf,
            "Referer": f"{self.base_url}/atlas",
        }

    def get_user_dashboards(self, search_term: str = "") -> list[dict[str, Any]]:
        """List Atlas dashboards for the authenticated user."""
        self._ensure_authenticated()
        params: dict[str, str] = {}
        if search_term:
            params["searchTerm"] = search_term

        with self._http_client() as client:
            headers = self._api_headers(client)
            response = client.get(
                f"{self.base_url}/atlas/user_dashboards",
                headers=headers,
                params=params or None,
            )
        if response.status_code != 200:
            raise AtlasClientError(
                f"Failed to fetch dashboards: {response.status_code} {response.text[:200]}"
            )
        payload = response.json()
        return list(payload.get("data", []))

    def resolve_dashboard(self, name_or_id: str | int) -> dict[str, Any]:
        """Resolve dashboard by numeric id or case-insensitive name match."""
        if isinstance(name_or_id, int) or str(name_or_id).isdigit():
            dashboard_id = int(name_or_id)
            dashboards = self.get_user_dashboards()
            for dashboard in dashboards:
                if dashboard.get("id") == dashboard_id:
                    return dashboard
            raise AtlasClientError(f"Atlas dashboard id not found: {dashboard_id}")

        needle = str(name_or_id).strip().lower()
        dashboards = self.get_user_dashboards()
        exact = [d for d in dashboards if d.get("name", "").lower() == needle]
        if exact:
            return exact[0]

        partial = [d for d in dashboards if needle in d.get("name", "").lower()]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            names = ", ".join(d.get("name", "") for d in partial)
            raise AtlasClientError(f"Multiple dashboards match '{name_or_id}': {names}")

        raise AtlasClientError(f"Atlas dashboard not found: {name_or_id}")

    def get_dashboard_widgets(self, name_or_id: str | int) -> dict[str, Any]:
        """Fetch dashboard metadata and widget definitions."""
        dashboard = self.resolve_dashboard(name_or_id)
        dashboard_id = int(dashboard["id"])

        self._ensure_authenticated()
        with self._http_client() as client:
            headers = self._api_headers(client)
            response = client.get(
                f"{self.base_url}/dashboard/{dashboard_id}/widgets",
                headers=headers,
            )
        if response.status_code != 200:
            raise AtlasClientError(
                f"Failed to fetch widgets: {response.status_code} {response.text[:200]}"
            )
        payload = response.json()
        return {
            "dashboard": payload.get("dashboard", dashboard),
            "widgets": payload.get("widgets", []),
        }

    @staticmethod
    def extract_symbols(widget_response: dict[str, Any]) -> list[str]:
        """Extract stock symbols from a widget /widget/process response."""
        symbols: list[str] = []

        groups = widget_response.get("groups")
        if isinstance(groups, list) and groups:
            if isinstance(groups[0], str):
                symbols.extend(str(s).strip().upper() for s in groups if s)

        group_data = widget_response.get("groupData")
        if isinstance(group_data, list):
            for item in group_data:
                name = item.get("name") if isinstance(item, dict) else None
                if name:
                    symbols.append(str(name).strip().upper())

        data = widget_response.get("data")
        if isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                sym = row.get("nsecode") or row.get("bsecode") or row.get("symbol")
                if sym:
                    symbols.append(str(sym).strip().upper())

        seen: set[str] = set()
        ordered: list[str] = []
        for symbol in symbols:
            if not symbol or symbol.startswith("*") or " " in symbol:
                continue
            if symbol not in seen:
                seen.add(symbol)
                ordered.append(symbol)
        return ordered

    def process_widget(self, widget: dict[str, Any]) -> dict[str, Any]:
        """Execute a single Atlas widget query and return symbols."""
        widget_id = widget.get("id")
        query = widget.get("query")
        if not query:
            raise AtlasClientError(f"Widget {widget_id} has no query")

        jsondetails = widget.get("jsondetails") or {}
        groups_meta = jsondetails.get("groups") or {}
        limit = groups_meta.get("limit", 50)
        size = groups_meta.get("size", 10)

        form_data = {
            "query": query,
            "use_live": "1",
            "limit": str(limit),
            "size": str(size),
            "widget_id": str(widget_id),
        }

        self._ensure_authenticated()
        with self._http_client() as client:
            headers = self._api_headers(client)
            response = client.post(
                f"{self.base_url}/widget/process",
                headers=headers,
                content=urlencode(form_data),
            )

        if response.status_code != 200:
            raise AtlasClientError(
                f"Widget process failed ({widget.get('name')}): "
                f"{response.status_code} {response.text[:200]}"
            )

        try:
            payload = response.json()
        except Exception as exc:
            raise AtlasClientError(f"Invalid widget response JSON: {exc}") from exc

        if isinstance(payload, dict) and payload.get("error"):
            raise AtlasClientError(str(payload["error"]))

        symbols = self.extract_symbols(payload if isinstance(payload, dict) else {})
        return {
            "widget_id": widget_id,
            "widget_name": widget.get("name"),
            "symbol_count": len(symbols),
            "symbols": symbols,
            "scan_link": payload.get("scan_link") if isinstance(payload, dict) else None,
            "raw": payload,
        }

    def run_dashboard(
        self,
        name_or_id: str | int,
        *,
        cache: bool = True,
        cache_ttl_minutes: int = 15,
    ) -> dict[str, Any]:
        """Run all widgets in a dashboard and return merged stock symbols."""
        dashboard_payload = self.get_dashboard_widgets(name_or_id)
        dashboard = dashboard_payload["dashboard"]
        widgets = dashboard_payload["widgets"]
        dashboard_id = int(dashboard["id"])
        dashboard_name = str(dashboard.get("name", dashboard_id))

        widget_results: list[dict[str, Any]] = []
        symbol_counter: Counter[str] = Counter()

        for widget in widgets:
            try:
                result = self.process_widget(widget)
                widget_results.append(result)
                for symbol in result["symbols"]:
                    symbol_counter[symbol] += 1
            except Exception as exc:
                logger.warning("Widget '{}' failed: {}", widget.get("name"), exc)
                widget_results.append(
                    {
                        "widget_id": widget.get("id"),
                        "widget_name": widget.get("name"),
                        "error": str(exc),
                        "symbols": [],
                        "symbol_count": 0,
                    }
                )

        merged_symbols = sorted(symbol_counter.keys())
        high_conviction = [
            {
                "symbol": symbol,
                "widget_hits": count,
                "conviction_score": round(min(100, count * 20), 2),
            }
            for symbol, count in symbol_counter.most_common()
            if count >= 2
        ]

        output: dict[str, Any] = {
            "dashboard_id": dashboard_id,
            "dashboard_name": dashboard_name,
            "dashboard_url": f"{self.base_url}/atlas",
            "widget_count": len(widgets),
            "widgets_executed": len(widget_results),
            "widgets": widget_results,
            "merged_symbols": merged_symbols,
            "merged_symbol_count": len(merged_symbols),
            "high_conviction": high_conviction,
        }

        if cache and self.repository:
            cache_key = f"atlas_dashboard:{dashboard_id}"
            self.repository.set_analysis_cache(
                cache_key,
                "atlas_dashboard_run",
                output,
                ttl_minutes=cache_ttl_minutes,
            )

        return output

    def get_dashboard_stocks(
        self,
        name_or_id: str | int,
        *,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Return merged stocks for a dashboard (cached or live)."""
        dashboard = self.resolve_dashboard(name_or_id)
        dashboard_id = int(dashboard["id"])

        if use_cache and self.repository:
            cached = self.repository.get_analysis_cache(f"atlas_dashboard:{dashboard_id}")
            if cached:
                payload = cached.payload_json
                return {
                    "dashboard_id": dashboard_id,
                    "dashboard_name": payload.get("dashboard_name"),
                    "source": "cache",
                    "merged_symbols": payload.get("merged_symbols", []),
                    "merged_symbol_count": payload.get("merged_symbol_count", 0),
                    "high_conviction": payload.get("high_conviction", []),
                }

        live = self.run_dashboard(name_or_id, cache=True)
        return {
            "dashboard_id": live["dashboard_id"],
            "dashboard_name": live["dashboard_name"],
            "source": "live",
            "merged_symbols": live["merged_symbols"],
            "merged_symbol_count": live["merged_symbol_count"],
            "high_conviction": live["high_conviction"],
        }

    def get_high_conviction_stocks(
        self,
        name_or_id: str | int,
        *,
        min_widget_hits: int = 2,
        use_cache: bool = True,
    ) -> list[dict[str, Any]]:
        """Stocks appearing in multiple dashboard widgets."""
        stocks = self.get_dashboard_stocks(name_or_id, use_cache=use_cache)
        return [
            item
            for item in stocks.get("high_conviction", [])
            if item.get("widget_hits", 0) >= min_widget_hits
        ]
