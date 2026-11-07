"""Stage-2 replay, summary, and cohort read APIs (WP11)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session

from surgisight.api.auth import decode_token
from surgisight.api.deps import get_current_user, record_access_log
from surgisight.analytics.lexicon import validate_object_lexicon
from surgisight.contract.models import (
    PerSecondRecord,
    PhasePrediction,
    ProducerInfo,
    StreamMessage,
    ToolPresencePrediction,
    Report,
)
from surgisight.contract.types import CONTRACT_VERSION, PHASE_ORDER, TOOL_ORDER, PhaseId
from surgisight.data.video import extract_frames
from surgisight.db import (
    AnalysisRunModel,
    CohortStatsModel,
    ReportModel,
    UserModel,
    VideoModel,
    get_db,
)
from surgisight.models.m2_phase.online import OnlinePhasePipeline
from surgisight.models.m2_phase.real_provider import RealPhaseProvider
from surgisight.report.summary import check_grounded_summary, generate_grounded_summary
from surgisight.settings import settings

router = APIRouter(tags=["stage-2"])


def prediction_to_record(raw: dict[str, Any], producer_version: str = "untrained-demo") -> PerSecondRecord:
    """Convert the exact OnlinePhasePipeline.step output to Data Contract v1.0."""
    phase_raw = raw["phase"]
    phase_values = phase_raw["probs"]
    tool_values = raw["tools"]
    if len(phase_values) != len(PHASE_ORDER) or len(tool_values) != len(TOOL_ORDER):
        raise ValueError("Online M2 output does not contain the seven contract classes.")

    phase_probs = {phase: float(phase_values[index]) for index, phase in enumerate(PHASE_ORDER)}
    phase_prediction = PhasePrediction(label=PhaseId(phase_raw["label"]), probs=phase_probs)
    tools_prediction = ToolPresencePrediction(
        probs={tool: float(tool_values[index]) for index, tool in enumerate(TOOL_ORDER)}
    )
    return PerSecondRecord(
        schema_version=CONTRACT_VERSION,
        producer=ProducerInfo(name="surgisight.models.m2_phase.online", version=producer_version),
        t=float(raw["t"]),
        frame_idx=raw.get("frame_idx"),
        phase=phase_prediction,
        tools=tools_prediction,
        triplets=raw.get("triplets", []),
        quality_flags=raw.get("quality_flags", []),
    )


def _crop_from_video(video: VideoModel) -> list[int]:
    """Normalize persisted crop_offset to the [x, y, width, height] representation."""
    crop = video.crop_offset
    if isinstance(crop, list) and len(crop) == 4:
        return [int(value) for value in crop]
    if isinstance(crop, dict):
        keys = ("x", "y", "w", "h")
        if all(key in crop for key in keys):
            return [int(crop[key]) for key in keys]
    return [0, 0, 0, 0]


def _load_replay_pipeline() -> tuple[OnlinePhasePipeline, str, str]:
    """Load a real M2 artifact when enabled; otherwise use the untrained demo path."""
    if settings.use_real_m2:
        provider = RealPhaseProvider()
        if provider.pipeline is not None:
            return provider.pipeline, provider.model_version, "real"
        # Do not silently represent the mock fallback as a trained model.
        demo = OnlinePhasePipeline(config={"feature_dim": 64, "temporal_decay": 0.85})
        return demo, "untrained-demo (artifact unavailable; deterministic baseline)", "demo"

    pipeline = OnlinePhasePipeline(config={"feature_dim": 64, "temporal_decay": 0.85})
    return pipeline, "untrained-demo (feature flag disabled; deterministic baseline)", "demo"


@router.websocket("/ws/replay/{session_id}")
async def replay_session(websocket: WebSocket, session_id: str) -> None:
    """Replay a stored local video through the same causal M2 step() method at 1 Hz.

    The client sends its short-lived access token in the first WebSocket message,
    avoiding a JWT in the URL. No video or prediction payload is sent to third parties.
    """
    await websocket.accept()
    db: Session = SyncSessionLocal()
    try:
        credentials = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
        token = credentials.get("token") if isinstance(credentials, dict) else None
        if not isinstance(token, str) or not token:
            await websocket.close(code=4401, reason="Missing access token.")
            return
        try:
            payload = decode_token(token, expected_type="access")
        except ValueError:
            await websocket.close(code=4401, reason="Invalid access token.")
            return

        user = db.execute(select(UserModel).where(UserModel.id == payload.get("sub"))).scalar_one_or_none()
        if user is None or not user.is_active:
            await websocket.close(code=4401, reason="Account is unavailable.")
            return
        run = db.execute(select(AnalysisRunModel).where(AnalysisRunModel.id == session_id)).scalar_one_or_none()
        if run is None:
            await websocket.close(code=4404, reason="Analysis run not found.")
            return
        video = db.execute(select(VideoModel).where(VideoModel.id == run.video_id)).scalar_one_or_none()
        if video is None:
            await websocket.close(code=4404, reason="Video metadata not found.")
            return

        video_path = Path(video.storage_path).resolve()
        storage_root = Path(settings.storage_dir).resolve()
        if not video_path.is_relative_to(storage_root) or not video_path.is_file():
            await websocket.close(code=4404, reason="Video is not available in configured local storage.")
            return

        from surgisight.api.deps import record_access_log

        record_access_log(db, action="websocket_replay", user_id=user.id, video_id=video.id)
        crop_offset = _crop_from_video(video)
        pipeline, model_version, model_mode = _load_replay_pipeline()
        pipeline.reset()

        wall_start = time.perf_counter()
        latencies: list[float] = []
        frame_count = 0
        for timestamp, frame_idx, frame in extract_frames(
            video_path, fps_target=1.0, crop_offset=crop_offset
        ):
            step_start = time.perf_counter()
            # OnlinePhasePipeline.step owns the sole training/serving transform path.
            raw_record = pipeline.step(frame, t=timestamp, frame_idx=frame_idx)
            latency_ms = (time.perf_counter() - step_start) * 1000.0
            latencies.append(latency_ms)
            record = prediction_to_record(raw_record, producer_version=model_version)
            message = StreamMessage(
                session_id=session_id,
                record=record,
                latency_ms=round(latency_ms, 3),
            )
            await websocket.send_json(message.model_dump(mode="json"))
            frame_count += 1

            target_elapsed = max(0.0, float(frame_count - 1))
            remaining = target_elapsed - (time.perf_counter() - wall_start)
            if remaining > 0:
                await asyncio.sleep(remaining)

        if latencies:
            p50 = float(np.percentile(latencies, 50))
            p95 = float(np.percentile(latencies, 95))
        else:
            p50 = p95 = 0.0
        await websocket.send_json(
            {
                "type": "replay_complete",
                "session_id": session_id,
                "model_version": model_version,
                "model_mode": model_mode,
                "frames": frame_count,
                "latency_ms": {"p50": round(p50, 3), "p95": round(p95, 3)},
                "ring_buffer_limit": pipeline.max_buffer_size,
                "ring_buffer_final_size": pipeline.get_buffer_size(),
            }
        )
    except WebSocketDisconnect:
        return
    except asyncio.TimeoutError:
        await websocket.close(code=4401, reason="Authentication message timed out.")
    except Exception as exc:
        try:
            await websocket.send_json({"type": "replay_error", "detail": str(exc)})
            await websocket.close(code=1011, reason="Replay could not be completed.")
        except Exception:
            return
    finally:
        db.close()


@router.get("/reports/{report_id}/summary")
def get_grounded_summary(
    report_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(get_current_user)],
) -> dict[str, object]:
    """Build and fact-check an AI-generated summary exclusively from persisted report JSON."""
    row = db.execute(select(ReportModel).where(ReportModel.id == report_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    run = db.execute(select(AnalysisRunModel).where(AnalysisRunModel.id == row.run_id)).scalar_one()
    report = Report.model_validate(row.report_json)
    validate_object_lexicon(report.model_dump(), path="report.json")
    summary = generate_grounded_summary(report)
    check = check_grounded_summary(summary, report)
    record_access_log(db, action="read_grounded_summary", user_id=user.id, video_id=run.video_id)
    if not check.accepted:
        return {"label": "AI-generated", "summary": None, "accepted": False, "reason": check.reason}
    return {
        "label": "AI-generated",
        "summary": summary,
        "accepted": True,
        "source": "persisted report.json",
    }


@router.get("/analytics/cohort")
def get_cohort_statistics(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[UserModel, Depends(get_current_user)],
    version: str | None = None,
) -> dict[str, object]:
    """Read-only cohort statistics view; no surgeon-level ranking is produced."""
    statement = select(CohortStatsModel).order_by(
        CohortStatsModel.version, CohortStatsModel.phase, CohortStatsModel.statistic
    )
    if version:
        statement = statement.where(CohortStatsModel.version == version)
    rows = db.execute(statement).scalars().all()
    record_access_log(db, action="read_cohort_statistics", user_id=user.id)
    return {
        "items": [
            {
                "version": item.version,
                "phase": item.phase,
                "statistic": item.statistic,
                "value": item.value,
                "n_videos": item.n_videos,
            }
            for item in rows
        ]
    }
