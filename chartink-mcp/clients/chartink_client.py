"""Chartink web client — reverse-engineered authenticated HTTP layer."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from app.config import get_settings
from auth.session_manager import AuthenticationError, SessionManager
from storage.models import Scan
from storage.repository import ChartinkRepository


class ChartinkClientError(Exception):
    """Raised when a Chartink client operation fails."""


class ChartinkClient:
    """HTTP client for Chartink with automatic session refresh."""

    KNOWN_ENDPOINTS = {
        "login": "/login",
        "dashboard": "/scan_dashboard",
        "screener_process": "/screener/process",
        "screener_index": "/screener",
        "alerts": "/alerts",
        "watchlists": "/watchlist",
        "profile": "/profile",
        "stock_search": "/api/search",
    }

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        repository: ChartinkRepository | None = None,
    ) -> None:
        self.settings = get_settings()
        self.session_manager = session_manager or SessionManager(repository=repository)
        self.repository = repository
        if repository and not self.session_manager.repository:
            self.session_manager.repository = repository

    @property
    def base_url(self) -> str:
        return self.settings.chartink_base_url.rstrip("/")

    def login(self, email: str | None = None, password: str | None = None) -> dict[str, str]:
        return self.session_manager.login(email, password)

    def logout(self) -> None:
        self.session_manager.logout()

    def is_authenticated(self) -> bool:
        self.session_manager.load_cookies()
        return self.session_manager.validate_session()

    def _ensure_authenticated(self) -> None:
        if not self.is_authenticated():
            self.session_manager.auto_reauthenticate()
            if not self.is_authenticated():
                raise AuthenticationError("Unable to establish authenticated Chartink session")

    def _request(
        self,
        method: str,
        path: str,
        *,
        referer: str | None = None,
        csrf: str | None = None,
        data: dict | None = None,
        json_body: dict | None = None,
    ) -> httpx.Response:
        self._ensure_authenticated()
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        headers: dict[str, str] = {
            "X-Requested-With": "XMLHttpRequest",
        }
        if referer:
            headers["Referer"] = referer
        if csrf:
            headers["X-CSRF-TOKEN"] = csrf
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        with self.session_manager.get_http_client() as client:
            response = client.request(
                method,
                url,
                headers=headers,
                data=data,
                json=json_body,
            )
            if response.status_code in (401, 403):
                logger.warning("Received {}, refreshing session", response.status_code)
                self.session_manager.refresh_session()
                with self.session_manager.get_http_client() as retry_client:
                    response = retry_client.request(
                        method,
                        url,
                        headers=headers,
                        data=data,
                        json=json_body,
                    )
            return response

    def _extract_csrf(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        meta = soup.find("meta", attrs={"name": "csrf-token"})
        if meta and meta.get("content"):
            return str(meta["content"])
        match = re.search(r'csrf-token["\']?\s*content=["\']([^"\']+)', html)
        if match:
            return match.group(1)
        raise ChartinkClientError("CSRF token not found on page")

    def _extract_scan_clause(self, html: str, slug: str) -> str | None:
        patterns = [
            r"scan_clause['\"]?\s*[:=]\s*['\"](\(.*?\))['\"]",
            r"data-scan-clause=['\"](\(.*?\))['\"]",
            r'"scan_clause"\s*:\s*"(\\\(.*?\\\))"',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                clause = match.group(1).replace("\\", "")
                return clause

        id_match = re.search(r"\{\s*(\d+)\s*\}", html)
        if id_match:
            scan_id = id_match.group(1)
            return f"( {{{scan_id}}} ( 1=1 ) )"

        logger.debug("Could not extract scan_clause for slug={}", slug)
        return None

    def get_profile(self) -> dict[str, Any]:
        """Fetch authenticated user profile information."""
        response = self._request("GET", self.KNOWN_ENDPOINTS["profile"])
        if response.status_code != 200:
            response = self._request("GET", self.KNOWN_ENDPOINTS["dashboard"])
        soup = BeautifulSoup(response.text, "html.parser")
        profile: dict[str, Any] = {
            "email": self.settings.chartink_email,
            "authenticated": True,
        }
        name_el = soup.select_one(".profile-name, .user-name, [data-user-name]")
        if name_el:
            profile["name"] = name_el.get_text(strip=True)
        plan_el = soup.select_one(".plan-name, .subscription-plan, [data-plan]")
        if plan_el:
            profile["plan"] = plan_el.get_text(strip=True)
        if self.repository and profile.get("email"):
            self.repository.get_or_create_user(
                email=str(profile["email"]),
                name=profile.get("name"),
            )
        return profile

    def get_all_scans(self, sync_db: bool = True) -> list[dict[str, Any]]:
        """Retrieve all scans accessible to the authenticated account."""
        scans: list[dict[str, Any]] = []
        pages = [
            self.KNOWN_ENDPOINTS["dashboard"],
            self.KNOWN_ENDPOINTS["screener_index"],
        ]
        seen_slugs: set[str] = set()

        for page_path in pages:
            response = self._request("GET", page_path)
            if response.status_code != 200:
                continue
            for scan in self._parse_scans_from_html(response.text, page_path):
                if scan["slug"] not in seen_slugs:
                    seen_slugs.add(scan["slug"])
                    scans.append(scan)

        if sync_db and self.repository:
            for scan_data in scans:
                self.repository.upsert_scan(
                    name=scan_data["name"],
                    slug=scan_data["slug"],
                    url=scan_data["url"],
                    scan_clause=scan_data.get("scan_clause"),
                    description=scan_data.get("description"),
                    metadata=scan_data.get("metadata"),
                )
        logger.info("Discovered {} scans", len(scans))
        return scans

    def _parse_scans_from_html(self, html: str, source_path: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        scans: list[dict[str, Any]] = []
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if "/screener/" not in href:
                continue
            if href.rstrip("/").endswith("/screener"):
                continue
            if any(x in href for x in ("/process", "/edit", "/clone", "/share")):
                continue
            full_url = urljoin(f"{self.base_url}/", href)
            parsed = urlparse(full_url)
            slug = parsed.path.rstrip("/").split("/")[-1]
            if not slug or slug == "screener":
                continue
            name = anchor.get_text(strip=True) or slug.replace("-", " ").title()
            scans.append(
                {
                    "name": name,
                    "slug": slug,
                    "url": full_url,
                    "source": source_path,
                    "metadata": {"discovered_from": source_path},
                }
            )
        return scans

    def search_scans(self, keyword: str) -> list[dict[str, Any]]:
        """Search scans by keyword in name or slug."""
        if self.repository:
            db_scans = self.repository.search_scans(keyword)
            if db_scans:
                return [self._scan_to_dict(s) for s in db_scans]
        all_scans = self.get_all_scans()
        keyword_lower = keyword.lower()
        return [
            s
            for s in all_scans
            if keyword_lower in s["name"].lower() or keyword_lower in s["slug"].lower()
        ]

    def _resolve_scan(self, scan_name: str) -> dict[str, Any]:
        if self.repository:
            db_scan = self.repository.get_scan_by_name(scan_name)
            if db_scan:
                return self._scan_to_dict(db_scan)
        matches = self.search_scans(scan_name)
        if not matches:
            all_scans = self.get_all_scans()
            slug = scan_name.lower().replace(" ", "-")
            direct = next((s for s in all_scans if s["slug"] == slug), None)
            if direct:
                return direct
            raise ChartinkClientError(f"Scan not found: {scan_name}")
        return matches[0]

    def run_scan(self, scan_name: str) -> dict[str, Any]:
        """Execute a scan by name and persist results."""
        scan = self._resolve_scan(scan_name)
        return self.run_scan_by_url(scan["url"], scan_name=scan["name"])

    def run_scan_by_url(
        self,
        scan_url: str,
        scan_name: str | None = None,
        scan_clause: str | None = None,
    ) -> dict[str, Any]:
        """Execute a scan by URL, optionally with explicit scan_clause."""
        if not scan_url.startswith("http"):
            scan_url = f"{self.base_url}/screener/{scan_url.lstrip('/')}"

        response = self._request("GET", scan_url, referer=scan_url)
        if response.status_code != 200:
            raise ChartinkClientError(f"Failed to load scan page: {response.status_code}")

        slug = urlparse(scan_url).path.rstrip("/").split("/")[-1]
        clause = scan_clause or self._extract_scan_clause(response.text, slug)
        if not clause:
            if self.repository:
                db_scan = self.repository.get_scan_by_slug(slug)
                if db_scan and db_scan.scan_clause:
                    clause = db_scan.scan_clause
        if not clause:
            raise ChartinkClientError(
                f"Could not determine scan_clause for {scan_url}. "
                "Run inspect_chartink.py or provide scan_clause explicitly."
            )

        csrf = self._extract_csrf(response.text)
        process_response = self._request(
            "POST",
            self.KNOWN_ENDPOINTS["screener_process"],
            referer=scan_url,
            csrf=csrf,
            data={"scan_clause": clause},
        )
        if process_response.status_code != 200:
            raise ChartinkClientError(
                f"Screener process failed: {process_response.status_code} "
                f"{process_response.text[:200]}"
            )

        payload = process_response.json()
        data = payload.get("data", [])
        records_total = payload.get("recordsTotal", len(data))
        name = scan_name or slug.replace("-", " ").title()

        if self.repository:
            db_scan = self.repository.upsert_scan(
                name=name,
                slug=slug,
                url=scan_url,
                scan_clause=clause,
            )
            self.repository.save_scan_result(
                scan_id=db_scan.id,
                results=data,
                records_total=records_total,
                raw_response=payload,
            )

        return {
            "scan_name": name,
            "scan_url": scan_url,
            "scan_clause": clause,
            "records_total": records_total,
            "results": data,
            "executed_at": payload.get("timestamp"),
        }

    def get_scan_results(self, scan_name: str) -> dict[str, Any]:
        """Return latest cached results or execute the scan."""
        if self.repository:
            db_scan = self.repository.get_scan_by_name(scan_name)
            if db_scan:
                latest = self.repository.get_latest_scan_result(db_scan.id)
                if latest and latest.results_json:
                    return {
                        "scan_name": db_scan.name,
                        "scan_url": db_scan.url,
                        "records_total": latest.records_total,
                        "results": latest.results_json,
                        "executed_at": latest.executed_at.isoformat(),
                        "source": "cache",
                    }
        return {**self.run_scan(scan_name), "source": "live"}

    def get_alerts(self, sync_db: bool = True) -> list[dict[str, Any]]:
        """Fetch user alerts from the alerts dashboard."""
        response = self._request("GET", self.KNOWN_ENDPOINTS["alerts"])
        alerts = self._parse_alerts_from_html(response.text)
        if sync_db and self.repository:
            self.repository.replace_alerts(alerts)
        return alerts

    def _parse_alerts_from_html(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        alerts: list[dict[str, Any]] = []
        rows = soup.select("table tbody tr, .alert-item, [data-alert-id]")
        for idx, row in enumerate(rows):
            name_el = row.select_one("a, .alert-name, td:first-child")
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name:
                continue
            scan_link = row.select_one("a[href*='/screener/']")
            scan_slug = None
            scan_url = None
            if scan_link and scan_link.get("href"):
                scan_url = urljoin(f"{self.base_url}/", scan_link["href"])
                scan_slug = urlparse(scan_url).path.rstrip("/").split("/")[-1]
            alerts.append(
                {
                    "id": row.get("data-alert-id") or str(idx),
                    "name": name,
                    "scan_name": scan_link.get_text(strip=True) if scan_link else None,
                    "scan_slug": scan_slug,
                    "scan_url": scan_url,
                    "is_active": "inactive" not in row.get_text(strip=True).lower(),
                }
            )
        return alerts

    def get_watchlists(self, sync_db: bool = True) -> list[dict[str, Any]]:
        """Fetch user watchlists."""
        response = self._request("GET", self.KNOWN_ENDPOINTS["watchlists"])
        watchlists = self._parse_watchlists_from_html(response.text)
        if sync_db and self.repository:
            self.repository.replace_watchlists(watchlists)
        return watchlists

    def _parse_watchlists_from_html(self, html: str) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        watchlists: list[dict[str, Any]] = []
        sections = soup.select(".watchlist-item, [data-watchlist-id], .watchlist table")
        if not sections:
            sections = soup.select("table.watchlist tbody tr")
        for idx, section in enumerate(sections):
            name_el = section.select_one("h3, h4, .watchlist-name, td:first-child, a")
            name = name_el.get_text(strip=True) if name_el else f"Watchlist {idx + 1}"
            symbols: list[str] = []
            for sym_el in section.select(".symbol, [data-symbol], td"):
                text = sym_el.get_text(strip=True)
                if text and text != name and len(text) <= 20:
                    if text.isupper() or re.match(r"^[A-Z0-9&-]+$", text):
                        symbols.append(text)
            watchlists.append(
                {
                    "id": section.get("data-watchlist-id") or str(idx),
                    "name": name,
                    "symbols": list(dict.fromkeys(symbols)),
                }
            )
        return watchlists

    def get_stock_details(self, symbol: str) -> dict[str, Any]:
        """Fetch stock details by symbol."""
        symbol = symbol.upper().strip()
        search_paths = [
            f"/stocks/{symbol}",
            f"/stock/{symbol}",
        ]
        for path in search_paths:
            response = self._request("GET", path)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                details: dict[str, Any] = {"symbol": symbol}
                for row in soup.select("table tr, .stock-detail-row"):
                    cells = row.find_all(["td", "th", "span"])
                    if len(cells) >= 2:
                        key = cells[0].get_text(strip=True).lower().replace(" ", "_")
                        val = cells[1].get_text(strip=True)
                        if key:
                            details[key] = val
                price_el = soup.select_one(".last-price, .stock-price, [data-last-price]")
                if price_el:
                    details["last_price"] = price_el.get_text(strip=True)
                return details

        try:
            response = self._request(
                "GET",
                f"{self.base_url}/screener/",
                referer=f"{self.base_url}/screener/",
            )
            csrf = self._extract_csrf(response.text)
            search_response = self._request(
                "POST",
                "/screener/process",
                referer=f"{self.base_url}/screener/",
                csrf=csrf,
                data={"scan_clause": f"( {{cash}} ( latest close > 0 and name like '%{symbol}%' ) )"},
            )
            if search_response.status_code == 200:
                data = search_response.json().get("data", [])
                match = next(
                    (r for r in data if r.get("nsecode", "").upper() == symbol),
                    data[0] if data else None,
                )
                if match:
                    return {"symbol": symbol, **match}
        except Exception as exc:
            logger.debug("Stock search fallback failed for {}: {}", symbol, exc)

        raise ChartinkClientError(f"Stock details not found for symbol: {symbol}")

    @staticmethod
    def _scan_to_dict(scan: Scan) -> dict[str, Any]:
        return {
            "name": scan.name,
            "slug": scan.slug,
            "url": scan.url,
            "scan_clause": scan.scan_clause,
            "description": scan.description,
            "metadata": scan.metadata_json,
            "last_synced_at": scan.last_synced_at.isoformat() if scan.last_synced_at else None,
        }

    def discover_endpoints(self) -> dict[str, Any]:
        """Discover accessible Chartink endpoints for inspection."""
        findings: dict[str, Any] = {"endpoints": [], "cookies": list(self.session_manager.get_cookies().keys())}
        for name, path in self.KNOWN_ENDPOINTS.items():
            try:
                response = self._request("GET", path)
                findings["endpoints"].append(
                    {
                        "name": name,
                        "path": path,
                        "status_code": response.status_code,
                        "content_type": response.headers.get("content-type"),
                        "reachable": response.status_code < 400,
                    }
                )
            except Exception as exc:
                findings["endpoints"].append(
                    {"name": name, "path": path, "reachable": False, "error": str(exc)}
                )
        return findings
