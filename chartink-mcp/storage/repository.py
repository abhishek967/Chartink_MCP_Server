"""Repository layer for Chartink Intelligence MCP persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session, sessionmaker

from storage.models import (
    Alert,
    AnalysisCache,
    CollectionRun,
    HistoricalResult,
    MarketSignal,
    Scan,
    ScanResult,
    SessionRecord,
    User,
    Watchlist,
    utcnow,
)


class ChartinkRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def _session(self) -> Session:
        return self._session_factory()

    def get_or_create_user(self, email: str, name: str | None = None) -> User:
        with self._session() as session:
            user = session.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(email=email, name=name)
                session.add(user)
                session.commit()
                session.refresh(user)
            elif name and user.name != name:
                user.name = name
                session.commit()
                session.refresh(user)
            return user

    def save_session(
        self,
        cookies: dict[str, Any],
        csrf_token: str | None = None,
        user_id: int | None = None,
        expires_at: datetime | None = None,
    ) -> SessionRecord:
        with self._session() as session:
            record = SessionRecord(
                user_id=user_id,
                cookies_json=cookies,
                csrf_token=csrf_token,
                is_valid=True,
                last_validated_at=utcnow(),
                expires_at=expires_at,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def get_latest_valid_session(self) -> SessionRecord | None:
        with self._session() as session:
            stmt = (
                select(SessionRecord)
                .where(SessionRecord.is_valid.is_(True))
                .order_by(desc(SessionRecord.updated_at))
                .limit(1)
            )
            return session.scalar(stmt)

    def invalidate_sessions(self) -> None:
        with self._session() as session:
            for record in session.scalars(select(SessionRecord)).all():
                record.is_valid = False
            session.commit()

    def mark_session_validated(self, session_id: int, valid: bool) -> None:
        with self._session() as session:
            record = session.get(SessionRecord, session_id)
            if record:
                record.is_valid = valid
                record.last_validated_at = utcnow()
                session.commit()

    def upsert_scan(
        self,
        name: str,
        slug: str,
        url: str,
        scan_clause: str | None = None,
        description: str | None = None,
        metadata: dict | None = None,
        user_id: int | None = None,
    ) -> Scan:
        with self._session() as session:
            scan = session.scalar(select(Scan).where(Scan.slug == slug))
            if scan is None:
                scan = Scan(
                    name=name,
                    slug=slug,
                    url=url,
                    scan_clause=scan_clause,
                    description=description,
                    metadata_json=metadata,
                    user_id=user_id,
                    last_synced_at=utcnow(),
                )
                session.add(scan)
            else:
                scan.name = name
                scan.url = url
                if scan_clause:
                    scan.scan_clause = scan_clause
                if description:
                    scan.description = description
                if metadata:
                    scan.metadata_json = metadata
                scan.last_synced_at = utcnow()
            session.commit()
            session.refresh(scan)
            return scan

    def get_scan_by_name(self, scan_name: str) -> Scan | None:
        with self._session() as session:
            scan = session.scalar(
                select(Scan).where(Scan.name.ilike(scan_name)).limit(1)
            )
            if scan:
                return scan
            slug = scan_name.lower().replace(" ", "-")
            return session.scalar(select(Scan).where(Scan.slug == slug).limit(1))

    def get_scan_by_slug(self, slug: str) -> Scan | None:
        with self._session() as session:
            return session.scalar(select(Scan).where(Scan.slug == slug).limit(1))

    def list_scans(self) -> list[Scan]:
        with self._session() as session:
            return list(session.scalars(select(Scan).order_by(Scan.name)).all())

    def search_scans(self, keyword: str) -> list[Scan]:
        with self._session() as session:
            pattern = f"%{keyword}%"
            stmt = select(Scan).where(
                Scan.name.ilike(pattern) | Scan.slug.ilike(pattern)
            )
            return list(session.scalars(stmt.order_by(Scan.name)).all())

    def save_scan_result(
        self,
        scan_id: int,
        results: list[dict[str, Any]],
        records_total: int,
        raw_response: dict | None = None,
    ) -> ScanResult:
        with self._session() as session:
            result = ScanResult(
                scan_id=scan_id,
                results_json=results,
                records_total=records_total,
                raw_response_json=raw_response,
            )
            session.add(result)
            session.commit()
            session.refresh(result)

            for row in results:
                symbol = row.get("nsecode") or row.get("bsecode") or row.get("name", "")
                historical = HistoricalResult(
                    scan_id=scan_id,
                    scan_result_id=result.id,
                    symbol=str(symbol),
                    nsecode=row.get("nsecode"),
                    bsecode=row.get("bsecode"),
                    close=_safe_float(row.get("close")),
                    per_chg=_safe_float(row.get("per_chg")),
                    volume=_safe_float(row.get("volume")),
                    sector=row.get("sector"),
                    metadata_json=row,
                )
                session.add(historical)
            session.commit()
            return result

    def get_latest_scan_result(self, scan_id: int) -> ScanResult | None:
        with self._session() as session:
            stmt = (
                select(ScanResult)
                .where(ScanResult.scan_id == scan_id)
                .order_by(desc(ScanResult.executed_at))
                .limit(1)
            )
            return session.scalar(stmt)

    def get_historical_results(
        self, scan_id: int | None = None, limit: int = 1000
    ) -> list[HistoricalResult]:
        with self._session() as session:
            stmt = select(HistoricalResult).order_by(desc(HistoricalResult.captured_at))
            if scan_id is not None:
                stmt = stmt.where(HistoricalResult.scan_id == scan_id)
            stmt = stmt.limit(limit)
            return list(session.scalars(stmt).all())

    def replace_alerts(self, alerts: list[dict[str, Any]]) -> list[Alert]:
        with self._session() as session:
            session.query(Alert).delete()
            records: list[Alert] = []
            for item in alerts:
                record = Alert(
                    external_id=item.get("id"),
                    name=item.get("name", "Unnamed Alert"),
                    scan_name=item.get("scan_name"),
                    scan_slug=item.get("scan_slug"),
                    scan_url=item.get("scan_url"),
                    webhook_url=item.get("webhook_url"),
                    is_active=item.get("is_active", True),
                    metadata_json=item,
                    synced_at=utcnow(),
                )
                session.add(record)
                records.append(record)
            session.commit()
            for record in records:
                session.refresh(record)
            return records

    def list_alerts(self) -> list[Alert]:
        with self._session() as session:
            return list(session.scalars(select(Alert).order_by(Alert.name)).all())

    def replace_watchlists(self, watchlists: list[dict[str, Any]]) -> list[Watchlist]:
        with self._session() as session:
            session.query(Watchlist).delete()
            records: list[Watchlist] = []
            for item in watchlists:
                record = Watchlist(
                    external_id=item.get("id"),
                    name=item.get("name", "Unnamed Watchlist"),
                    symbols_json=item.get("symbols", []),
                    metadata_json=item,
                    synced_at=utcnow(),
                )
                session.add(record)
                records.append(record)
            session.commit()
            for record in records:
                session.refresh(record)
            return records

    def list_watchlists(self) -> list[Watchlist]:
        with self._session() as session:
            return list(session.scalars(select(Watchlist).order_by(Watchlist.name)).all())

    def get_analysis_cache(self, cache_key: str) -> AnalysisCache | None:
        with self._session() as session:
            cache = session.scalar(
                select(AnalysisCache).where(AnalysisCache.cache_key == cache_key)
            )
            expires_at = _normalize_utc(cache.expires_at) if cache else None
            if cache and expires_at and expires_at < utcnow():
                session.delete(cache)
                session.commit()
                return None
            return cache

    def set_analysis_cache(
        self,
        cache_key: str,
        analysis_type: str,
        payload: dict[str, Any],
        ttl_minutes: int = 15,
    ) -> AnalysisCache:
        with self._session() as session:
            existing = session.scalar(
                select(AnalysisCache).where(AnalysisCache.cache_key == cache_key)
            )
            expires_at = utcnow() + timedelta(minutes=ttl_minutes)
            if existing:
                existing.payload_json = payload
                existing.analysis_type = analysis_type
                existing.expires_at = expires_at
                session.commit()
                session.refresh(existing)
                return existing
            cache = AnalysisCache(
                cache_key=cache_key,
                analysis_type=analysis_type,
                payload_json=payload,
                expires_at=expires_at,
            )
            session.add(cache)
            session.commit()
            session.refresh(cache)
            return cache

    def create_collection_run(
        self,
        run_uuid: str,
        collection_date: str,
        scans_configured: list[str],
    ) -> CollectionRun:
        with self._session() as session:
            run = CollectionRun(
                run_uuid=run_uuid,
                collection_date=collection_date,
                status="running",
                scans_configured=list(scans_configured),
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            return run

    def get_completed_run_for_date(self, collection_date: str) -> CollectionRun | None:
        with self._session() as session:
            stmt = (
                select(CollectionRun)
                .where(
                    CollectionRun.collection_date == collection_date,
                    CollectionRun.status == "completed",
                )
                .order_by(desc(CollectionRun.completed_at))
                .limit(1)
            )
            return session.scalar(stmt)

    def complete_collection_run(
        self,
        run_id: int,
        *,
        scans_succeeded: int,
        scans_failed: int,
        stocks_saved: int,
        execution_seconds: float,
        summary: dict[str, Any],
        error_message: str | None = None,
        status: str = "completed",
    ) -> CollectionRun | None:
        with self._session() as session:
            run = session.get(CollectionRun, run_id)
            if run is None:
                return None
            run.status = status
            run.completed_at = utcnow()
            run.scans_succeeded = scans_succeeded
            run.scans_failed = scans_failed
            run.stocks_saved = stocks_saved
            run.execution_seconds = execution_seconds
            run.summary_json = summary
            run.error_message = error_message
            session.commit()
            session.refresh(run)
            return run

    def save_market_signal(
        self,
        run_id: int,
        *,
        symbol: str,
        company_name: str | None,
        sector: str | None,
        close_price: float | None,
        triggered_scans: list[str],
        scan_count: int,
        score_breakdown: dict[str, Any],
        final_score: float,
        rs_rating: int | None = None,
        eps_rating: int | None = None,
        composite_rating: int | None = None,
        industry_rank: int | None = None,
        accumulation_distribution: str | None = None,
        pattern_type: str | None = None,
        market_outlook: str | None = None,
    ) -> MarketSignal | None:
        """Insert a market signal; skip if (run_id, symbol) already exists."""
        symbol = symbol.upper().strip()
        with self._session() as session:
            existing = session.scalar(
                select(MarketSignal).where(
                    MarketSignal.run_id == run_id,
                    MarketSignal.symbol == symbol,
                )
            )
            if existing is not None:
                return None
            signal = MarketSignal(
                run_id=run_id,
                symbol=symbol,
                company_name=company_name,
                sector=sector,
                close_price=close_price,
                triggered_scans=list(triggered_scans),
                scan_count=scan_count,
                score_breakdown=score_breakdown,
                final_score=final_score,
                rs_rating=rs_rating,
                eps_rating=eps_rating,
                composite_rating=composite_rating,
                industry_rank=industry_rank,
                accumulation_distribution=accumulation_distribution,
                pattern_type=pattern_type,
                market_outlook=market_outlook,
            )
            session.add(signal)
            session.commit()
            session.refresh(signal)
            return signal

    def count_signals_for_run(self, run_id: int) -> int:
        with self._session() as session:
            return len(
                list(
                    session.scalars(
                        select(MarketSignal).where(MarketSignal.run_id == run_id)
                    ).all()
                )
            )

    def list_signals_for_run(self, run_id: int) -> list[MarketSignal]:
        with self._session() as session:
            stmt = (
                select(MarketSignal)
                .where(MarketSignal.run_id == run_id)
                .order_by(desc(MarketSignal.final_score))
            )
            return list(session.scalars(stmt).all())


def _normalize_utc(dt: datetime | None) -> datetime | None:
    """Normalize datetimes for safe comparison (SQLite may return naive values)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
