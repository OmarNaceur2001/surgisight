"""SQLAlchemy 2.0 relational models for SurgiSight.

Enforces:
- Schema Contract v1.0 compatibility
- Portable JSON storage via JSON_VARIANT (JSONB on PostgreSQL, JSON on SQLite)
- Foreign keys and indexing on high-frequency search tables
- Append-only constraints on `corrections` (P6)
- Audited access via `access_log` (P7)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from surgisight.db.base import JSON_VARIANT, Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class UserModel(Base):
    """User account model with role-based access control (P7)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    videos: Mapped[list[VideoModel]] = relationship("VideoModel", back_populates="uploader")
    corrections: Mapped[list[CorrectionModel]] = relationship(
        "CorrectionModel", back_populates="author"
    )


class VideoModel(Base):
    """Ingested surgical video metadata (media stored on filesystem/storage, not DB)."""

    __tablename__ = "videos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    global_video_id: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    dataset: Mapped[str] = mapped_column(String(64), nullable=False, default="cholec80")
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    fps: Mapped[float] = mapped_column(Float, nullable=False, default=25.0)
    crop_offset: Mapped[dict[str, Any] | list[int]] = mapped_column(JSON_VARIANT, nullable=False)
    uploaded_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    uploader: Mapped[UserModel | None] = relationship("UserModel", back_populates="videos")
    analysis_runs: Mapped[list[AnalysisRunModel]] = relationship(
        "AnalysisRunModel", back_populates="video"
    )


class AnalysisRunModel(Base):
    """Execution run of the offline or recorded analysis pipeline."""

    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    video_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("videos.id"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    stage: Mapped[str] = mapped_column(String(64), default="init", nullable=False)
    contract_version: Mapped[str] = mapped_column(String(16), default="1.0", nullable=False)
    model_versions: Mapped[dict[str, Any]] = mapped_column(
        JSON_VARIANT, default=dict, nullable=False
    )
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    video: Mapped[VideoModel] = relationship("VideoModel", back_populates="analysis_runs")
    report: Mapped[ReportModel | None] = relationship(
        "ReportModel", back_populates="run", uselist=False
    )
    phase_segments: Mapped[list[PhaseSegmentModel]] = relationship(
        "PhaseSegmentModel", back_populates="run"
    )
    tool_intervals: Mapped[list[ToolIntervalModel]] = relationship(
        "ToolIntervalModel", back_populates="run"
    )
    events: Mapped[list[EventModel]] = relationship("EventModel", back_populates="run")
    triplets: Mapped[list[TripletIndexModel]] = relationship(
        "TripletIndexModel", back_populates="run"
    )


class ReportModel(Base):
    """Operative Report row referencing report.json source of truth."""

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id"), unique=True, index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="DRAFT_PENDING_REVIEW", nullable=False)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, nullable=False)
    pdf_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_check: Mapped[dict[str, Any] | None] = mapped_column(JSON_VARIANT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationships
    run: Mapped[AnalysisRunModel] = relationship("AnalysisRunModel", back_populates="report")
    corrections: Mapped[list[CorrectionModel]] = relationship(
        "CorrectionModel", back_populates="report"
    )


class CorrectionModel(Base):
    """Expert review corrections table. Strictly append-only (P6)."""

    __tablename__ = "corrections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    report_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reports.id"), index=True, nullable=False
    )
    author_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True, nullable=False
    )
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    before: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, nullable=False)
    after: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    report: Mapped[ReportModel] = relationship("ReportModel", back_populates="corrections")
    author: Mapped[UserModel] = relationship("UserModel", back_populates="corrections")


class PhaseSegmentModel(Base):
    """Relational search index for phase segments."""

    __tablename__ = "phase_segments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id"), index=True, nullable=False
    )
    label: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    start: Mapped[float] = mapped_column(Float, nullable=False)
    end: Mapped[float] = mapped_column(Float, nullable=False)
    conf: Mapped[float] = mapped_column(Float, nullable=False)
    uncertain: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    run: Mapped[AnalysisRunModel] = relationship(
        "AnalysisRunModel", back_populates="phase_segments"
    )


class ToolIntervalModel(Base):
    """Relational search index for instrument active presence intervals."""

    __tablename__ = "tool_intervals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id"), index=True, nullable=False
    )
    tool: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    start: Mapped[float] = mapped_column(Float, nullable=False)
    end: Mapped[float] = mapped_column(Float, nullable=False)

    run: Mapped[AnalysisRunModel] = relationship(
        "AnalysisRunModel", back_populates="tool_intervals"
    )


class EventModel(Base):
    """Relational search index for detected clinical events."""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id"), index=True, nullable=False
    )
    type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    t: Mapped[float] = mapped_column(Float, index=True, nullable=False)
    conf: Mapped[float] = mapped_column(Float, nullable=False)
    uncertain: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSON_VARIANT, default=list, nullable=False)

    run: Mapped[AnalysisRunModel] = relationship("AnalysisRunModel", back_populates="events")


class TripletIndexModel(Base):
    """Relational search index for top action triplets (timestamp search)."""

    __tablename__ = "triplet_index"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analysis_runs.id"), index=True, nullable=False
    )
    t: Mapped[float] = mapped_column(Float, index=True, nullable=False)
    ivt_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)

    run: Mapped[AnalysisRunModel] = relationship("AnalysisRunModel", back_populates="triplets")


class CohortStatsModel(Base):
    """Reference cohort statistics for robust deviation detection (P3)."""

    __tablename__ = "cohort_stats"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    version: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    phase: Mapped[str | None] = mapped_column(String(8), index=True, nullable=True)
    statistic: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    n_videos: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AccessLogModel(Base):
    """Audit log for media, report, and video accesses (P7)."""

    __tablename__ = "access_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    video_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("videos.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


# Compound indexes for fast search queries
Index("ix_triplet_run_id_t", TripletIndexModel.run_id, TripletIndexModel.t)
Index("ix_phase_run_id_label", PhaseSegmentModel.run_id, PhaseSegmentModel.label)
Index("ix_tool_run_id_tool", ToolIntervalModel.run_id, ToolIntervalModel.tool)
Index("ix_access_log_ts", AccessLogModel.ts)
