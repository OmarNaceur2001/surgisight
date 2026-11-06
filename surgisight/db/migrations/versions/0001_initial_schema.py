"""Initial schema with 11 tables and search indexes.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-06 16:15:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_variant = sa.JSON().with_variant(postgresql.JSONB, "postgresql")


def upgrade() -> None:
    # 1. users
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # 2. videos
    op.create_table(
        "videos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("global_video_id", sa.String(128), nullable=False),
        sa.Column("dataset", sa.String(64), nullable=False, server_default="cholec80"),
        sa.Column("storage_path", sa.String(512), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=False),
        sa.Column("fps", sa.Float(), nullable=False, server_default="25.0"),
        sa.Column("crop_offset", json_variant, nullable=False),
        sa.Column("uploaded_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_videos_global_video_id", "videos", ["global_video_id"], unique=True)

    # 3. analysis_runs
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("video_id", sa.String(36), sa.ForeignKey("videos.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("stage", sa.String(64), nullable=False, server_default="init"),
        sa.Column("contract_version", sa.String(16), nullable=False, server_default="1.0"),
        sa.Column("model_versions", json_variant, nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_analysis_runs_video_id", "analysis_runs", ["video_id"])
    op.create_index(
        "ix_analysis_runs_idempotency_key", "analysis_runs", ["idempotency_key"], unique=True
    )

    # 4. reports
    op.create_table(
        "reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="DRAFT_PENDING_REVIEW"),
        sa.Column("report_json", json_variant, nullable=False),
        sa.Column("pdf_path", sa.String(512), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("summary_check", json_variant, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reports_run_id", "reports", ["run_id"], unique=True)

    # 5. corrections (P6 append-only)
    op.create_table(
        "corrections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("report_id", sa.String(36), sa.ForeignKey("reports.id"), nullable=False),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_ref", sa.String(128), nullable=False),
        sa.Column("before", json_variant, nullable=False),
        sa.Column("after", json_variant, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_corrections_report_id", "corrections", ["report_id"])
    op.create_index("ix_corrections_author_id", "corrections", ["author_id"])

    # 6. phase_segments
    op.create_table(
        "phase_segments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("label", sa.String(8), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("start", sa.Float(), nullable=False),
        sa.Column("end", sa.Float(), nullable=False),
        sa.Column("conf", sa.Float(), nullable=False),
        sa.Column("uncertain", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_phase_segments_run_id", "phase_segments", ["run_id"])
    op.create_index("ix_phase_segments_label", "phase_segments", ["label"])

    # 7. tool_intervals
    op.create_table(
        "tool_intervals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("tool", sa.String(32), nullable=False),
        sa.Column("start", sa.Float(), nullable=False),
        sa.Column("end", sa.Float(), nullable=False),
    )
    op.create_index("ix_tool_intervals_run_id", "tool_intervals", ["run_id"])
    op.create_index("ix_tool_intervals_tool", "tool_intervals", ["tool"])

    # 8. events
    op.create_table(
        "events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("t", sa.Float(), nullable=False),
        sa.Column("conf", sa.Float(), nullable=False),
        sa.Column("uncertain", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("evidence", json_variant, nullable=False),
    )
    op.create_index("ix_events_run_id", "events", ["run_id"])
    op.create_index("ix_events_type", "events", ["type"])
    op.create_index("ix_events_t", "events", ["t"])

    # 9. triplet_index
    op.create_table(
        "triplet_index",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("t", sa.Float(), nullable=False),
        sa.Column("ivt_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
    )
    op.create_index("ix_triplet_index_run_id", "triplet_index", ["run_id"])
    op.create_index("ix_triplet_index_t", "triplet_index", ["t"])
    op.create_index("ix_triplet_index_ivt_id", "triplet_index", ["ivt_id"])

    # 10. cohort_stats
    op.create_table(
        "cohort_stats",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("phase", sa.String(8), nullable=True),
        sa.Column("statistic", sa.String(64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("n_videos", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_cohort_stats_version", "cohort_stats", ["version"])
    op.create_index("ix_cohort_stats_phase", "cohort_stats", ["phase"])

    # 11. access_log
    op.create_table(
        "access_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("video_id", sa.String(36), sa.ForeignKey("videos.id"), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_access_log_ts", "access_log", ["ts"])


def downgrade() -> None:
    op.drop_table("access_log")
    op.drop_table("cohort_stats")
    op.drop_table("triplet_index")
    op.drop_table("events")
    op.drop_table("tool_intervals")
    op.drop_table("phase_segments")
    op.drop_table("corrections")
    op.drop_table("reports")
    op.drop_table("analysis_runs")
    op.drop_table("videos")
    op.drop_table("users")
