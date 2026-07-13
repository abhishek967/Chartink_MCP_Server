"""SQLAlchemy ORM models for Chartink Intelligence MCP."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    plan: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    sessions: Mapped[list[SessionRecord]] = relationship(back_populates="user")
    scans: Mapped[list[Scan]] = relationship(back_populates="user")


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    cookies_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    csrf_token: Mapped[str | None] = mapped_column(String(512))
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User | None] = relationship(back_populates="sessions")


class Scan(Base):
    __tablename__ = "scans"
    __table_args__ = (UniqueConstraint("slug", name="uq_scans_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    slug: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    scan_clause: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User | None] = relationship(back_populates="scans")
    results: Mapped[list[ScanResult]] = relationship(back_populates="scan")


class ScanResult(Base):
    __tablename__ = "scan_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id"), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    records_total: Mapped[int] = mapped_column(Integer, default=0)
    results_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    raw_response_json: Mapped[dict | None] = mapped_column(JSON)

    scan: Mapped[Scan] = relationship(back_populates="results")
    historical: Mapped[list[HistoricalResult]] = relationship(back_populates="scan_result")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str | None] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    scan_name: Mapped[str | None] = mapped_column(String(512))
    scan_slug: Mapped[str | None] = mapped_column(String(512))
    scan_url: Mapped[str | None] = mapped_column(String(1024))
    webhook_url: Mapped[str | None] = mapped_column(String(1024))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str | None] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    symbols_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AnalysisCache(Base):
    __tablename__ = "analysis_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    analysis_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HistoricalResult(Base):
    __tablename__ = "historical_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id"), nullable=False)
    scan_result_id: Mapped[int | None] = mapped_column(
        ForeignKey("scan_results.id"), nullable=True
    )
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    nsecode: Mapped[str | None] = mapped_column(String(64))
    bsecode: Mapped[str | None] = mapped_column(String(64))
    close: Mapped[float | None] = mapped_column(Float)
    per_chg: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    sector: Mapped[str | None] = mapped_column(String(256))
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scan_result: Mapped[ScanResult | None] = relationship(back_populates="historical")


class CollectionRun(Base):
    """One daily (or on-demand) market collection execution."""

    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_uuid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    collection_date: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    scans_configured: Mapped[list | None] = mapped_column(JSON)
    scans_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    scans_failed: Mapped[int] = mapped_column(Integer, default=0)
    stocks_saved: Mapped[int] = mapped_column(Integer, default=0)
    execution_seconds: Mapped[float | None] = mapped_column(Float)
    summary_json: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    signals: Mapped[list["MarketSignal"]] = relationship(
        "MarketSignal", back_populates="run"
    )


class MarketSignal(Base):
    """Merged cross-scan stock signal for a single collection run."""

    __tablename__ = "market_signals"
    __table_args__ = (
        UniqueConstraint("run_id", "symbol", name="uq_market_signals_run_symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("collection_runs.id"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    company_name: Mapped[str | None] = mapped_column(String(255))
    sector: Mapped[str | None] = mapped_column(String(256))
    close_price: Mapped[float | None] = mapped_column(Float)
    triggered_scans: Mapped[list | None] = mapped_column(JSON)
    scan_count: Mapped[int] = mapped_column(Integer, default=0)
    score_breakdown: Mapped[dict | None] = mapped_column(JSON)
    final_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Future MarketSmith (nullable)
    rs_rating: Mapped[int | None] = mapped_column(Integer)
    eps_rating: Mapped[int | None] = mapped_column(Integer)
    composite_rating: Mapped[int | None] = mapped_column(Integer)
    industry_rank: Mapped[int | None] = mapped_column(Integer)
    accumulation_distribution: Mapped[str | None] = mapped_column(String(64))
    pattern_type: Mapped[str | None] = mapped_column(String(128))
    market_outlook: Mapped[str | None] = mapped_column(String(128))

    # Optional performance tracking (filled by later jobs)
    return_5d: Mapped[float | None] = mapped_column(Float)
    return_20d: Mapped[float | None] = mapped_column(Float)
    return_60d: Mapped[float | None] = mapped_column(Float)

    run: Mapped["CollectionRun"] = relationship(
        "CollectionRun", back_populates="signals"
    )
