"""Paced, causal live replay through the exported OnlinePhasePipeline.step API."""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterable
from typing import Any

import numpy as np

from surgisight.analytics.latency import LATENCY_METRICS
from surgisight.contract.models import (
    PerSecondRecord,
    PhasePrediction,
    ProducerInfo,
    StreamMessage,
    ToolPresencePrediction,
)
from surgisight.contract.types import PHASE_ORDER, TOOL_ORDER, PhaseId
from surgisight.models.m2_phase.online import OnlinePhasePipeline


def _to_contract_record(raw: dict[str, Any]) -> PerSecondRecord:
    """Convert unchanged online.py output into the public data-contract model."""
    raw_phase = raw["phase"]
    raw_phase_probs = raw_phase["probs"]
    raw_tool_probs = raw["tools"]
    if len(raw_phase_probs) != len(PHASE_ORDER) or len(raw_tool_probs) != len(TOOL_ORDER):
        raise ValueError("Online pipeline output does not match the 7-phase / 7-tool contract")
    phase_probs = {
        phase: float(raw_phase_probs[index]) for index, phase in enumerate(PHASE_ORDER)
    }
    tool_probs = {
        tool: float(raw_tool_probs[index]) for index, tool in enumerate(TOOL_ORDER)
    }
    return PerSecondRecord(
        producer=ProducerInfo(name="surgisight.models.m2_phase.online", version="1.0"),
        t=float(raw["t"]),
        frame_idx=int(raw["frame_idx"]) if raw.get("frame_idx") is not None else None,
        phase=PhasePrediction(label=PhaseId(raw_phase["label"]), probs=phase_probs),
        tools=ToolPresencePrediction(probs=tool_probs),
        triplets=[],
        quality_flags=list(raw.get("quality_flags", [])),
    )


def _next_frame(iterator: Any) -> tuple[float, int, np.ndarray] | None:
    """Advance a synchronous decoder in a worker thread."""
    try:
        return next(iterator)
    except StopIteration:
        return None


async def iter_online_replay(
    session_id: str,
    frames: Iterable[tuple[float, int, np.ndarray]],
    pipeline: OnlinePhasePipeline,
    speed: float = 1.0,
) -> AsyncIterator[StreamMessage]:
    """Run one causal step per sampled frame and pace output against video time."""
    if not 0.1 <= speed <= 8.0:
        raise ValueError("speed must be between 0.1 and 8")
    pipeline.reset()
    wall_start = time.monotonic()
    first_video_t: float | None = None
    frame_iterator = iter(frames)
    while True:
        frame = await asyncio.to_thread(_next_frame, frame_iterator)
        if frame is None:
            break
        t, frame_idx, frame_rgb = frame
        if first_video_t is None:
            first_video_t = float(t)
        target_wall = wall_start + (float(t) - first_video_t) / speed
        delay = target_wall - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        started = time.perf_counter()
        raw = pipeline.step(
            np.asarray(frame_rgb, dtype=np.uint8),
            t=float(t),
            frame_idx=int(frame_idx),
        )
        record = _to_contract_record(raw)
        latency_ms = (time.perf_counter() - started) * 1000.0
        LATENCY_METRICS.record("m2_online_step", latency_ms)
        yield StreamMessage(session_id=session_id, record=record, latency_ms=latency_ms)
