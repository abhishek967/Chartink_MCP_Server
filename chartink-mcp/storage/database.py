"""SQLAlchemy database engine and session factory."""

from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import PROJECT_ROOT, get_settings
from storage.models import Base


def _ensure_sqlite_directory(database_url: str) -> None:
    if database_url.startswith("sqlite:///"):
        db_path = database_url.replace("sqlite:///", "", 1)
        path = PROJECT_ROOT / db_path if not db_path.startswith("/") else None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # noqa: ARG001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    _ensure_sqlite_directory(settings.database_url)
    settings.cookies_file.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=get_engine())


def get_db_session() -> Generator[Session, None, None]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
