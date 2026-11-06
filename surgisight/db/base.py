"""SQLAlchemy 2.0 declarative base and custom column types.

Provides portable JSON support:
- PostgreSQL uses native JSONB for fast indexing and query capabilities.
- SQLite uses standard JSON text storage with transparent JSON serialization.
"""

from __future__ import annotations

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

# Dual-dialect JSON type: JSONB on PostgreSQL, JSON on SQLite/other
JSON_VARIANT = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    """Base declarative class for all SurgiSight database models."""

    pass
