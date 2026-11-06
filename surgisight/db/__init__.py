"""SurgiSight Database subpackage.

Provides:
- Declarative Base and JSON_VARIANT column type
- Relational models for users, videos, runs, reports, corrections, search indexes
- Sync and async session providers
- DatabaseService enforcing append-only rules and index population
"""

from __future__ import annotations

from surgisight.db.base import JSON_VARIANT, Base
from surgisight.db.models import (
    AccessLogModel,
    AnalysisRunModel,
    CohortStatsModel,
    CorrectionModel,
    EventModel,
    PhaseSegmentModel,
    ReportModel,
    ToolIntervalModel,
    TripletIndexModel,
    UserModel,
    VideoModel,
)
from surgisight.db.service import (
    POSTGRES_APPEND_ONLY_TRIGGER_SQL,
    AppendOnlyViolationError,
    DatabaseService,
    verify_correction_mutation_forbidden,
)
from surgisight.db.session import (
    SyncSessionLocal,
    create_async_db_engine,
    create_sync_engine,
    get_async_database_url,
    get_db,
    get_sync_database_url,
    init_db,
)

__all__ = [
    "POSTGRES_APPEND_ONLY_TRIGGER_SQL",
    "AccessLogModel",
    "AnalysisRunModel",
    "AppendOnlyViolationError",
    "Base",
    "CohortStatsModel",
    "CorrectionModel",
    "DatabaseService",
    "EventModel",
    "JSON_VARIANT",
    "PhaseSegmentModel",
    "ReportModel",
    "SyncSessionLocal",
    "ToolIntervalModel",
    "TripletIndexModel",
    "UserModel",
    "VideoModel",
    "create_async_db_engine",
    "create_sync_engine",
    "get_async_database_url",
    "get_db",
    "get_sync_database_url",
    "init_db",
    "verify_correction_mutation_forbidden",
]
