"""Database connection engines and session factories.

Supports both synchronous operations (worker, CLI, migrations) and
asynchronous operations (FastAPI endpoints).
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from surgisight.db.base import Base
from surgisight.settings import settings


def get_sync_database_url() -> str:
    """Normalize database URL for synchronous drivers."""
    url = settings.database_url
    if url.startswith("sqlite+aiosqlite:"):
        return url.replace("sqlite+aiosqlite:", "sqlite:")
    if url.startswith("postgresql+psycopg_async:"):
        return url.replace("postgresql+psycopg_async:", "postgresql+psycopg:")
    return url


def get_async_database_url() -> str:
    """Normalize database URL for asynchronous drivers."""
    url = settings.database_url
    if url.startswith("sqlite:") and not url.startswith("sqlite+aiosqlite:"):
        return url.replace("sqlite:", "sqlite+aiosqlite:")
    if url.startswith("postgresql+psycopg:") and not url.startswith("postgresql+psycopg://"):
        return url
    return url


def create_sync_engine(url: str | None = None, **kwargs: Any) -> Engine:
    target_url = url or get_sync_database_url()
    return create_engine(target_url, **kwargs)


def create_async_db_engine(url: str | None = None, **kwargs: Any) -> AsyncEngine:
    target_url = url or get_async_database_url()
    return create_async_engine(target_url, **kwargs)


# Global sync session factory
_sync_engine = create_sync_engine()
SyncSessionLocal = sessionmaker(bind=_sync_engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI synchronous DB session dependency."""
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(engine: Engine | None = None) -> None:
    """Create all tables on target engine (used in tests and dev bootstrap)."""
    target = engine or _sync_engine
    Base.metadata.create_all(bind=target)
