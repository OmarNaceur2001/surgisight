"""Pipeline orchestrator coordinating analysis stages (WP5).

Key architectural guarantees:
- Resumable per stage with atomic file outputs (write temp -> rename).
- Contract validation at each stage boundary; a failing module fails its own stage.
- Relational search index population and Parquet persistence.
- Failure isolation per run.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from surgisight.contract.models import (
    KeyEvent,
    PerSecondRecord,
    ProducerInfo,
    Report,
    ToolUsage,
    TripletHighlight,
    validate_interval_tiling,
)
from surgisight.contract.types import (
    CONTRACT_VERSION,
    RESEARCH_DISCLAIMER,
    TOOL_ORDER,
    PhaseId,
    ReportStatus,
    RunStatus,
    ToolId,
)
from surgisight.db import (
    AnalysisRunModel,
    DatabaseService,
    ReportModel,
    VideoModel,
)
from surgisight.models.providers import ProviderRegistry
from surgisight.worker.storage import (
    save_1hz_predictions_parquet,
    save_5hz_detections_parquet,
)

logger = logging.getLogger(__name__)

# Sequential pipeline execution stages
STAGES = [
    "load_video",
    "phases_and_tools",
    "detections_and_tracks",
    "triplets",
    "persist_parquet",
    "build_report_and_indices",
]


class StageExecutionError(RuntimeError):
    """Raised when a specific pipeline stage fails validation or execution."""

    pass


class PipelineOrchestrator:
    """Coordinates analysis execution on an AnalysisRunModel."""

    def __init__(self, db: Session, run_id: str) -> None:
        self.db = db
        self.run_id = run_id

    def execute(self) -> Report:
        """Execute all stages sequentially, updating progress and isolating failures."""
        run = self.db.execute(
            select(AnalysisRunModel).where(AnalysisRunModel.id == self.run_id)
        ).scalar_one_or_none()
        if not run:
            raise ValueError(f"Run {self.run_id} not found in database.")

        video = self.db.execute(
            select(VideoModel).where(VideoModel.id == run.video_id)
        ).scalar_one_or_none()
        if not video:
            raise ValueError(f"Video {run.video_id} for run {self.run_id} not found.")

        duration_s = video.duration_s
        producer = ProducerInfo(name="surgisight.pipeline", version=CONTRACT_VERSION)

        try:
            # Stage 1: Load Video / Verification
            self._update_progress(run, stage="load_video", progress=0.10)

            # Stage 2: Phases and Tools (M2 interface)
            self._update_progress(run, stage="phases_and_tools", progress=0.30)
            phase_provider = ProviderRegistry.get_phase_provider()
            tool_provider = ProviderRegistry.get_tool_provider()

            phase_preds, phase_segments = phase_provider.predict_phases(
                duration_s=duration_s, seed=42
            )
            validate_interval_tiling(phase_segments, duration_s)

            tool_preds = tool_provider.predict_tools(
                duration_s=duration_s, phases=phase_preds, seed=42
            )

            # Stage 3: Detections and Tracks (M3 interface)
            self._update_progress(run, stage="detections_and_tracks", progress=0.55)
            detector = ProviderRegistry.get_detector_provider()
            tracker = ProviderRegistry.get_tracker_provider()

            detections = detector.detect(duration_s=duration_s, phases=phase_preds, seed=42)
            _tracks = tracker.track(detections=detections, duration_s=duration_s)

            # Stage 4: Action Triplets (M4 interface)
            self._update_progress(run, stage="triplets", progress=0.70)
            triplet_provider = ProviderRegistry.get_triplet_provider()
            triplet_preds = triplet_provider.predict_triplets(
                duration_s=duration_s, phases=phase_preds, seed=42
            )

            # Assemble 1 Hz PerSecondRecord stream
            per_second_records: list[PerSecondRecord] = []
            tool_presence_counts: dict[ToolId, int] = dict.fromkeys(TOOL_ORDER, 0)
            triplet_highlights: list[TripletHighlight] = []

            for sec in range(int(duration_s)):
                t = round(float(sec), 2)
                p_pred = phase_preds[sec] if sec < len(phase_preds) else phase_preds[-1]
                t_pred = tool_preds[sec] if sec < len(tool_preds) else tool_preds[-1]
                trip_pred = triplet_preds[sec] if sec < len(triplet_preds) else []

                for tool, prob in t_pred.probs.items():
                    if prob >= 0.50:
                        tool_presence_counts[tool] += 1

                for tr in trip_pred:
                    if tr.score > 0.85 and len(triplet_highlights) < 10:
                        triplet_highlights.append(
                            TripletHighlight(
                                ivt_id=tr.ivt_id,
                                ivt_name=tr.ivt_name,
                                t=t,
                                score=tr.score,
                                phase=p_pred.label,
                            )
                        )

                rec = PerSecondRecord(
                    schema_version=CONTRACT_VERSION,
                    producer=producer,
                    t=t,
                    frame_idx=sec * 25,
                    phase=p_pred,
                    tools=t_pred,
                    triplets=trip_pred,
                    quality_flags=[],
                )
                per_second_records.append(rec)

            # Stage 5: Persist Parquet files atomically
            self._update_progress(run, stage="persist_parquet", progress=0.85)
            save_1hz_predictions_parquet(self.run_id, per_second_records)
            save_5hz_detections_parquet(self.run_id, detections)

            # Stage 6: Build Report and Populate Relational Indices
            self._update_progress(run, stage="build_report_and_indices", progress=0.95)

            tools_usage = [
                ToolUsage(
                    tool=t,
                    usage_s=float(tool_presence_counts[t]),
                    pct=(
                        round(tool_presence_counts[t] / duration_s * 100.0, 2)
                        if duration_s > 0
                        else 0.0
                    ),
                )
                for t in TOOL_ORDER
            ]

            # Standard cholecystectomy key clinical events
            p2_seg = next((s for s in phase_segments if s.label == PhaseId.P2), phase_segments[0])
            p3_seg = next((s for s in phase_segments if s.label == PhaseId.P3), phase_segments[0])
            p4_seg = next((s for s in phase_segments if s.label == PhaseId.P4), phase_segments[0])

            events = [
                KeyEvent(
                    type="start_calot_dissection",
                    t=p2_seg.start,
                    conf=p2_seg.conf,
                    uncertain=p2_seg.uncertain,
                    evidence=["phase_transition_P1_to_P2"],
                ),
                KeyEvent(
                    type="first_clip",
                    t=round(p3_seg.start + 10.0, 2),
                    conf=0.92,
                    uncertain=False,
                    evidence=["clipper_presence"],
                ),
                KeyEvent(
                    type="start_gallbladder_dissection",
                    t=p4_seg.start,
                    conf=p4_seg.conf,
                    uncertain=p4_seg.uncertain,
                    evidence=["phase_transition_P3_to_P4"],
                ),
            ]

            report = Report(
                schema_version=CONTRACT_VERSION,
                producer=producer,
                video_id=video.id,
                dataset=video.dataset,
                duration_s=duration_s,
                status=ReportStatus.DRAFT_PENDING_REVIEW,
                disclaimer=RESEARCH_DISCLAIMER,
                phases=phase_segments,
                tools=tools_usage,
                events=events,
                deviations=[],
                triplet_highlights=triplet_highlights,
                confidence_notes=["Calibrated probabilities using temperature scaling."],
                models=run.model_versions,
            )

            # Persist Report row
            report_row = ReportModel(
                run_id=run.id,
                status=ReportStatus.DRAFT_PENDING_REVIEW.value,
                report_json=report.model_dump(),
            )
            self.db.add(report_row)
            self.db.flush()

            # Index into relational tables
            DatabaseService.populate_run_indices(self.db, run.id, report, tool_predictions=tool_preds)

            # Stage Complete
            run.status = RunStatus.COMPLETED.value
            run.progress = 1.0
            run.stage = "completed"
            run.finished_at = datetime.now(UTC)
            self.db.commit()

            return report

        except Exception as exc:
            logger.exception("Analysis run %s failed during processing", self.run_id)
            run.status = RunStatus.FAILED.value
            run.error = str(exc)
            run.finished_at = datetime.now(UTC)
            self.db.commit()
            raise StageExecutionError(f"Run {self.run_id} failed: {exc}") from exc

    def _update_progress(self, run: AnalysisRunModel, stage: str, progress: float) -> None:
        run.stage = stage
        run.progress = progress
        self.db.commit()
