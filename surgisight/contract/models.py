"""Pydantic v2 data models for SurgiSight Data Contract v1.0.

Time and interval conventions:
- Primary key: `t` in seconds (float, 2 decimals, from video start).
- Intervals are half-open: [start, end) in seconds.
- Phase segments must tile the video completely: [0.0, duration_s) with no gap and no overlap.
- Separate streams: 1 Hz PerSecondRecord, 5 Hz DetectionRecord, Tracks.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from surgisight.contract.types import (
    CONTRACT_VERSION,
    PHASE_NAMES,
    PHASE_ORDER,
    RESEARCH_DISCLAIMER,
    TOOL_ORDER,
    PhaseId,
    QualityFlag,
    ReportStatus,
    RunStatus,
    TargetType,
    ToolId,
)


class ProducerInfo(BaseModel):
    """Metadata of the module producing the record/file."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Module or service name")
    version: str = Field(..., description="Semantic or git version")


class TimeInterval(BaseModel):
    """Half-open interval [start, end) in seconds."""

    model_config = ConfigDict(frozen=True)

    start: float = Field(..., ge=0.0, description="Start time in seconds (inclusive)")
    end: float = Field(..., gt=0.0, description="End time in seconds (exclusive)")

    @field_validator("start", "end")
    @classmethod
    def round_time(cls, v: float) -> float:
        return round(float(v), 2)

    @model_validator(mode="after")
    def validate_order(self) -> TimeInterval:
        if self.end <= self.start:
            raise ValueError(
                f"Invalid interval: start ({self.start} s) must be strictly less than end ({self.end} s)"
            )
        return self

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 2)

    def contains(self, t: float) -> bool:
        """Check if time t is within half-open interval [start, end)."""
        return self.start <= round(t, 2) < self.end


class PhasePrediction(BaseModel):
    """Phase prediction for a single time step."""

    model_config = ConfigDict(frozen=True)

    label: PhaseId = Field(..., description="Predicted phase ID (P1..P7)")
    probs: dict[PhaseId, float] = Field(
        ..., description="Calibrated probabilities across all 7 phases"
    )

    @field_validator("probs")
    @classmethod
    def validate_probs(cls, probs: dict[PhaseId, float]) -> dict[PhaseId, float]:
        missing = [p for p in PHASE_ORDER if p not in probs]
        if missing:
            raise ValueError(f"Phase probabilities must contain all 7 phases; missing: {missing}")
        rounded = {k: round(float(v), 4) for k, v in probs.items()}
        total = sum(rounded.values())
        if not (0.95 <= total <= 1.05):
            raise ValueError(f"Phase probabilities must sum to approximately 1.0 (got {total:.4f})")
        return rounded

    @property
    def name(self) -> str:
        return PHASE_NAMES[self.label]

    @property
    def confidence(self) -> float:
        return self.probs[self.label]


class ToolPresencePrediction(BaseModel):
    """Presence probabilities for the 7 tracked surgical instruments."""

    model_config = ConfigDict(frozen=True)

    probs: dict[ToolId, float] = Field(
        ..., description="Presence probability for each of the 7 instruments [0..1]"
    )

    @field_validator("probs")
    @classmethod
    def validate_tool_probs(cls, probs: dict[ToolId, float]) -> dict[ToolId, float]:
        missing = [t for t in TOOL_ORDER if t not in probs]
        if missing:
            raise ValueError(f"Tool probabilities must contain all 7 tools; missing: {missing}")
        for tool, p in probs.items():
            if not (0.0 <= p <= 1.0):
                raise ValueError(f"Probability for {tool} must be in [0, 1], got {p}")
        return {k: round(float(v), 4) for k, v in probs.items()}

    def is_present(self, tool: ToolId, threshold: float = 0.5) -> bool:
        return self.probs.get(tool, 0.0) >= threshold


class TripletPrediction(BaseModel):
    """Action triplet <instrument, verb, target> prediction."""

    model_config = ConfigDict(frozen=True)

    ivt_id: int = Field(..., ge=0, description="Official numeric identifier")
    ivt_name: str = Field(
        ...,
        description="Human-readable triplet string, e.g., 'grasper,grasp,gallbladder'",
    )
    score: float = Field(..., ge=0.0, le=1.0, description="Prediction confidence score")

    @field_validator("score")
    @classmethod
    def round_score(cls, v: float) -> float:
        return round(float(v), 4)


class PerSecondRecord(BaseModel):
    """1 Hz primary synchronized analysis record.

    Primary key is `t` (seconds from video start, float rounded to 2 decimals).
    """

    model_config = ConfigDict(frozen=True)

    schema_version: str = Field(default=CONTRACT_VERSION, description="Contract version (1.0)")
    producer: ProducerInfo = Field(..., description="Module/version that emitted this record")
    t: float = Field(..., ge=0.0, description="Time in seconds from video start")
    frame_idx: int | None = Field(
        default=None, ge=0, description="Original 25 FPS frame index (optional)"
    )
    phase: PhasePrediction = Field(..., description="Phase prediction and probabilities")
    tools: ToolPresencePrediction = Field(..., description="Tool presence probabilities")
    triplets: list[TripletPrediction] = Field(
        default_factory=list, description="Top triplet predictions at time t"
    )
    quality_flags: list[QualityFlag] = Field(
        default_factory=list, description="Optical quality alerts (smoke, blur, etc.)"
    )

    @field_validator("t")
    @classmethod
    def round_t(cls, v: float) -> float:
        return round(float(v), 2)


class DetectionRecord(BaseModel):
    """5 Hz spatial tool detection record with bounding box."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = Field(default=CONTRACT_VERSION)
    producer: ProducerInfo = Field(...)
    t: float = Field(..., ge=0.0, description="Time in seconds from video start")
    tool: ToolId = Field(..., description="Detected surgical instrument")
    bbox: list[float] = Field(
        ...,
        description="Bounding box [x1, y1, x2, y2] in cropped frame pixels",
    )
    score: float = Field(..., ge=0.0, le=1.0, description="Detection confidence")
    track_id: int | None = Field(
        default=None, description="Trajectory track identifier if linked by tracker"
    )

    @field_validator("t")
    @classmethod
    def round_t(cls, v: float) -> float:
        return round(float(v), 2)

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, box: list[float]) -> list[float]:
        if len(box) != 4:
            raise ValueError(f"bbox must have 4 coordinates [x1, y1, x2, y2], got {len(box)}")
        x1, y1, x2, y2 = box
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"Invalid bbox coordinates: x2 > x1 and y2 > y1 required, got {box}")
        return [round(float(c), 1) for c in box]


class Track(BaseModel):
    """Spatial-temporal track of an instrument across half-open time intervals."""

    model_config = ConfigDict(frozen=True)

    track_id: int = Field(..., ge=0)
    tool: ToolId = Field(...)
    intervals: list[TimeInterval] = Field(
        default_factory=list, description="Active presence time intervals [start, end)"
    )


class PhaseSegment(BaseModel):
    """Continuous phase segment [start, end) on the operative timeline."""

    model_config = ConfigDict(frozen=True)

    label: PhaseId = Field(..., description="Phase ID (P1..P7)")
    name: str = Field(..., description="Official phase name")
    start: float = Field(..., ge=0.0, description="Start second (inclusive)")
    end: float = Field(..., gt=0.0, description="End second (exclusive)")
    conf: float = Field(
        ..., ge=0.0, le=1.0, description="Minimum calibrated confidence over segment evidence"
    )
    uncertain: bool = Field(
        default=False, description="Flagged uncertain if conf < calibrated threshold"
    )

    @field_validator("start", "end")
    @classmethod
    def round_time(cls, v: float) -> float:
        return round(float(v), 2)

    @model_validator(mode="after")
    def validate_segment(self) -> PhaseSegment:
        if self.end <= self.start:
            raise ValueError(f"Phase segment end ({self.end}) must be > start ({self.start})")
        expected_name = PHASE_NAMES[self.label]
        if self.name != expected_name:
            # Enforce canonical name
            object.__setattr__(self, "name", expected_name)
        return self

    @property
    def duration_s(self) -> float:
        return round(self.end - self.start, 2)


def validate_interval_tiling(
    segments: list[PhaseSegment], duration_s: float, tolerance: float = 0.05
) -> None:
    """Verify that phase segments tile [0.0, duration_s) with NO gap and NO overlap.

    Raises ValueError on tiling violation.
    """
    if not segments:
        raise ValueError("Segments list cannot be empty for tiling verification")

    sorted_segs = sorted(segments, key=lambda s: s.start)

    # First segment must start at 0.0
    if abs(sorted_segs[0].start - 0.0) > tolerance:
        raise ValueError(
            f"Tiling violation: first segment starts at {sorted_segs[0].start}s, expected 0.0s"
        )

    # Consecutive segments must touch: seg[i].end == seg[i+1].start
    for i in range(len(sorted_segs) - 1):
        current = sorted_segs[i]
        next_seg = sorted_segs[i + 1]
        gap = next_seg.start - current.end
        if abs(gap) > tolerance:
            if gap > 0:
                raise ValueError(
                    f"Tiling gap of {gap:.2f}s between segment {current.label} (ends at {current.end}s) "
                    f"and {next_seg.label} (starts at {next_seg.start}s)"
                )
            else:
                raise ValueError(
                    f"Tiling overlap of {-gap:.2f}s between segment {current.label} (ends at {current.end}s) "
                    f"and {next_seg.label} (starts at {next_seg.start}s)"
                )

    # Last segment must end at duration_s
    last = sorted_segs[-1]
    if abs(last.end - duration_s) > tolerance:
        raise ValueError(
            f"Tiling violation: last segment ends at {last.end}s, video duration is {duration_s}s"
        )


class ToolUsage(BaseModel):
    """Cumulative usage statistics for a surgical instrument."""

    model_config = ConfigDict(frozen=True)

    tool: ToolId = Field(...)
    usage_s: float = Field(..., ge=0.0, description="Total active duration in seconds")
    pct: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Percentage of total video duration (Note: does NOT sum to 100% across tools)",
    )

    @field_validator("usage_s", "pct")
    @classmethod
    def round_metrics(cls, v: float) -> float:
        return round(float(v), 2)


class KeyEvent(BaseModel):
    """Discrete key clinical event detected on the surgical timeline."""

    model_config = ConfigDict(frozen=True)

    type: str = Field(..., description="Event identifier, e.g. 'first_clip'")
    t: float = Field(..., ge=0.0, description="Timestamp in seconds")
    conf: float = Field(..., ge=0.0, le=1.0, description="Calibrated event confidence")
    uncertain: bool = Field(default=False, description="Flagged uncertain if below threshold")
    evidence: list[str] = Field(
        default_factory=list, description="Traceable evidence items (e.g. tool presence, triplets)"
    )

    @field_validator("t")
    @classmethod
    def round_t(cls, v: float) -> float:
        return round(float(v), 2)


class Deviation(BaseModel):
    """Observed deviation from reference cohort statistics (neutral phrasing, P3)."""

    model_config = ConfigDict(frozen=True)

    type: str = Field(..., description="Deviation type, e.g. 'phase_duration'")
    phase: PhaseId | None = Field(default=None, description="Associated phase if applicable")
    value_s: float = Field(..., description="Observed duration/value in seconds")
    cohort_p95_s: float | None = Field(
        default=None, description="95th percentile observed in reference cohort"
    )
    cohort_n: int = Field(default=0, ge=0, description="Cohort sample size")
    wording: str = Field(
        ...,
        description="Neutral wording strictly conforming to wording_lexicon.yaml (P3)",
    )


class TripletHighlight(BaseModel):
    """Key action triplet highlight for summary and report."""

    model_config = ConfigDict(frozen=True)

    ivt_id: int = Field(...)
    ivt_name: str = Field(...)
    t: float = Field(..., ge=0.0)
    score: float = Field(..., ge=0.0, le=1.0)
    phase: PhaseId | None = Field(default=None)


class Report(BaseModel):
    """Operative Report schema (M6 / JSON source of truth, P4).

    Every figure appearing in the PDF must trace directly to this schema.
    """

    schema_version: str = Field(default=CONTRACT_VERSION)
    producer: ProducerInfo = Field(...)
    video_id: str = Field(..., description="Unique video identifier")
    dataset: str = Field(..., description="Source dataset name, e.g. 'cholec80'")
    duration_s: float = Field(..., gt=0.0, description="Total video duration in seconds")
    status: ReportStatus = Field(
        default=ReportStatus.DRAFT_PENDING_REVIEW,
        description="Report review lifecycle status",
    )
    disclaimer: str = Field(
        default=RESEARCH_DISCLAIMER,
        description="Mandatory research use only disclaimer (P1)",
    )
    phases: list[PhaseSegment] = Field(..., description="Phase segments that tile [0, duration_s)")
    tools: list[ToolUsage] = Field(..., description="Per-tool usage duration and percentage")
    events: list[KeyEvent] = Field(default_factory=list, description="Detected key surgical events")
    deviations: list[Deviation] = Field(
        default_factory=list, description="Reference cohort statistical deviations"
    )
    triplet_highlights: list[TripletHighlight] = Field(
        default_factory=list, description="Prominent action triplets"
    )
    cvs: dict[str, Any] | None = Field(
        default=None, description="Critical View of Safety assessment (Stage 2 stub)"
    )
    confidence_notes: list[str] = Field(
        default_factory=list, description="Calibrated confidence explanations"
    )
    models: dict[str, str] = Field(
        default_factory=dict, description="Version dictionary of inference models used"
    )
    summary: str | None = Field(default=None, description="AI-generated textual summary (Stage 2)")

    @field_validator("duration_s")
    @classmethod
    def round_duration(cls, v: float) -> float:
        return round(float(v), 2)

    @model_validator(mode="after")
    def validate_tiling(self) -> Report:
        validate_interval_tiling(self.phases, self.duration_s)
        return self


class Correction(BaseModel):
    """Append-only correction record proposed by expert reviewer (P6)."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Unique correction UUID")
    report_id: str = Field(..., description="Target report UUID")
    author_id: str = Field(..., description="Author user UUID")
    target_type: TargetType = Field(..., description="Entity type being corrected")
    target_ref: str = Field(..., description="Identifier of target entity or phase index")
    before: dict[str, Any] = Field(..., description="State before correction")
    after: dict[str, Any] = Field(..., description="Corrected state")
    reason: str = Field(..., description="Clinical justification for change")
    created_at: str = Field(..., description="ISO 8601 creation timestamp")


class StreamMessage(BaseModel):
    """WebSocket streaming message (live replay or online inference)."""

    model_config = ConfigDict(frozen=True)

    type: str = Field(default="per_second_record")
    session_id: str = Field(...)
    record: PerSecondRecord = Field(...)
    latency_ms: float = Field(default=0.0, ge=0.0)


class VideoMeta(BaseModel):
    """Normalized video metadata extracted during ingest."""

    model_config = ConfigDict(frozen=True)

    fps: float = Field(..., gt=0.0)
    duration_s: float = Field(..., gt=0.0)
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    crop_offset: list[int] = Field(
        ...,
        description="Black-border crop coordinates [x, y, cropped_width, cropped_height]",
    )
    source: str = Field(..., description="Filename or source identifier")
    frame_count: int = Field(..., ge=0)

    @field_validator("crop_offset")
    @classmethod
    def validate_crop(cls, v: list[int]) -> list[int]:
        if len(v) != 4:
            raise ValueError(f"crop_offset must be [x, y, w, h], got {v}")
        return v


class AnalysisRun(BaseModel):
    """Analysis job execution state tracked in DB and worker."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(...)
    video_id: str = Field(...)
    status: RunStatus = Field(default=RunStatus.PENDING)
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    stage: str = Field(default="init")
    contract_version: str = Field(default=CONTRACT_VERSION)
    model_versions: dict[str, str] = Field(default_factory=dict)
    config_hash: str = Field(...)
    idempotency_key: str = Field(...)
    started_at: str | None = Field(default=None)
    finished_at: str | None = Field(default=None)
    error: str | None = Field(default=None)


# Time-to-frame conversion helpers
def seconds_to_frame_idx(t: float, fps: float = 25.0) -> int:
    """Convert timestamp in seconds to 0-based frame index."""
    if t < 0:
        raise ValueError(f"Timestamp must be non-negative, got {t}")
    return int(math.floor(round(t, 2) * fps))


def frame_idx_to_seconds(frame_idx: int, fps: float = 25.0) -> float:
    """Convert 0-based frame index to seconds (2 decimals)."""
    if frame_idx < 0:
        raise ValueError(f"Frame index must be non-negative, got {frame_idx}")
    return round(frame_idx / fps, 2)
