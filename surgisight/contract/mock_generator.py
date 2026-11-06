"""Deterministic mock generator for realistic synthetic cholecystectomy video analyses.

Follows Data Contract v1.0 specifications:
- Phases P1..P7 in physiological sequence
- Correlated instrument presence per phase
- Realistic action triplets <instrument, verb, target>
- 5 Hz detection bounding boxes and trajectories
- Tiling phase segments [0.0, duration_s) with no gap/overlap
- Deterministic output given the same random seed.
"""

from __future__ import annotations

import random
from typing import NamedTuple

from surgisight.contract.models import (
    DetectionRecord,
    Deviation,
    KeyEvent,
    PerSecondRecord,
    PhasePrediction,
    PhaseSegment,
    ProducerInfo,
    Report,
    TimeInterval,
    ToolPresencePrediction,
    ToolUsage,
    Track,
    TripletHighlight,
    TripletPrediction,
    VideoMeta,
)
from surgisight.contract.types import (
    CONTRACT_VERSION,
    PHASE_NAMES,
    PHASE_ORDER,
    RESEARCH_DISCLAIMER,
    TOOL_ORDER,
    PhaseId,
    ReportStatus,
    ToolId,
)

# Reference proportions of surgical phases in laparoscopic cholecystectomy
PHASE_PROPORTIONS: dict[PhaseId, tuple[float, float]] = {
    PhaseId.P1: (0.05, 0.08),  # Preparation (5-8%)
    PhaseId.P2: (0.22, 0.32),  # Calot dissection (22-32%)
    PhaseId.P3: (0.06, 0.12),  # Clipping and cutting (6-12%)
    PhaseId.P4: (0.25, 0.35),  # Gallbladder dissection (25-35%)
    PhaseId.P5: (0.05, 0.09),  # Packaging (5-9%)
    PhaseId.P6: (0.08, 0.14),  # Cleaning and coagulation (8-14%)
    PhaseId.P7: (0.03, 0.06),  # Retraction (3-6%)
}

# Typical tools active during each phase (probability ranges)
PHASE_TOOL_CORRELATIONS: dict[PhaseId, dict[ToolId, float]] = {
    PhaseId.P1: {ToolId.GRASPER: 0.70, ToolId.HOOK: 0.10},
    PhaseId.P2: {ToolId.GRASPER: 0.85, ToolId.HOOK: 0.75, ToolId.BIPOLAR: 0.35},
    PhaseId.P3: {ToolId.GRASPER: 0.80, ToolId.CLIPPER: 0.70, ToolId.SCISSORS: 0.65},
    PhaseId.P4: {ToolId.GRASPER: 0.88, ToolId.HOOK: 0.80, ToolId.BIPOLAR: 0.30},
    PhaseId.P5: {ToolId.GRASPER: 0.75, ToolId.SPECIMEN_BAG: 0.85},
    PhaseId.P6: {
        ToolId.IRRIGATOR: 0.70,
        ToolId.HOOK: 0.40,
        ToolId.BIPOLAR: 0.30,
        ToolId.GRASPER: 0.50,
    },
    PhaseId.P7: {ToolId.GRASPER: 0.60, ToolId.SPECIMEN_BAG: 0.70},
}

# Clinically relevant triplets per phase
PHASE_TRIPLETS: dict[PhaseId, list[tuple[int, str]]] = {
    PhaseId.P1: [(1, "grasper,grasp,gallbladder")],
    PhaseId.P2: [
        (2, "grasper,retract,gallbladder"),
        (3, "hook,dissect,calot_triangle"),
        (4, "bipolar,coagulate,calot_triangle"),
    ],
    PhaseId.P3: [
        (5, "clipper,clip,cystic_duct"),
        (6, "scissors,cut,cystic_duct"),
        (7, "clipper,clip,cystic_artery"),
        (8, "scissors,cut,cystic_artery"),
    ],
    PhaseId.P4: [
        (9, "hook,dissect,liver_bed"),
        (10, "grasper,retract,liver"),
        (11, "bipolar,coagulate,liver_bed"),
    ],
    PhaseId.P5: [
        (12, "grasper,insert,specimen_bag"),
        (13, "grasper,pack,gallbladder"),
    ],
    PhaseId.P6: [
        (14, "irrigator,aspirate,fluid"),
        (15, "irrigator,irrigate,abdominal_cavity"),
        (16, "bipolar,coagulate,liver_bed"),
    ],
    PhaseId.P7: [
        (17, "grasper,retract,specimen_bag"),
    ],
}


class MockAnalysisResult(NamedTuple):
    report: Report
    per_second_records: list[PerSecondRecord]
    detection_records: list[DetectionRecord]
    tracks: list[Track]
    video_meta: VideoMeta


def generate_mock_analysis(
    duration_minutes: float = 35.0,
    seed: int = 42,
    video_id: str = "mock_cholec_01",
    dataset: str = "cholec80_synthetic",
) -> MockAnalysisResult:
    """Generate realistic, deterministic synthetic surgical video analysis data.

    Args:
        duration_minutes: Video length in minutes (typically 20..90).
        seed: Random seed for deterministic generation.
        video_id: Unique video identifier.
        dataset: Source research dataset name.
    """
    rng = random.Random(seed)
    total_duration_s = round(float(duration_minutes * 60.0), 2)
    producer = ProducerInfo(name="surgisight.mock_generator", version=CONTRACT_VERSION)

    # 1. Allocate phase durations that sum exactly to total_duration_s
    raw_weights = [
        rng.uniform(PHASE_PROPORTIONS[p][0], PHASE_PROPORTIONS[p][1]) for p in PHASE_ORDER
    ]
    norm_factor = sum(raw_weights)
    target_durations = [round(w / norm_factor * total_duration_s, 2) for w in raw_weights]

    # Adjust rounding remainder to ensure exact tiling to the last second
    diff = round(total_duration_s - sum(target_durations), 2)
    target_durations[-1] = round(target_durations[-1] + diff, 2)

    # 2. Build perfectly tiled PhaseSegment list
    phase_segments: list[PhaseSegment] = []
    current_time = 0.0
    for phase_id, dur in zip(PHASE_ORDER, target_durations, strict=True):
        start_t = round(current_time, 2)
        end_t = round(current_time + dur, 2)
        if end_t > total_duration_s or phase_id == PHASE_ORDER[-1]:
            end_t = total_duration_s

        conf = round(rng.uniform(0.72, 0.98), 4)
        uncertain = conf < 0.50  # Using standard threshold 0.50

        segment = PhaseSegment(
            label=phase_id,
            name=PHASE_NAMES[phase_id],
            start=start_t,
            end=end_t,
            conf=conf,
            uncertain=uncertain,
        )
        phase_segments.append(segment)
        current_time = end_t

    # 3. Generate 1 Hz PerSecondRecord stream
    per_second_records: list[PerSecondRecord] = []
    tool_presence_counts: dict[ToolId, int] = dict.fromkeys(TOOL_ORDER, 0)
    triplet_highlights: list[TripletHighlight] = []

    for sec in range(int(total_duration_s)):
        t = round(float(sec), 2)

        # Find active phase segment
        active_phase = PhaseId.P1
        for seg in phase_segments:
            if seg.start <= t < seg.end:
                active_phase = seg.label
                break

        # Generate phase probabilities with dominant active_phase
        base_probs: dict[PhaseId, float] = {}
        for p in PHASE_ORDER:
            if p == active_phase:
                base_probs[p] = rng.uniform(0.70, 0.95)
            else:
                base_probs[p] = rng.uniform(0.005, 0.05)
        prob_sum = sum(base_probs.values())
        norm_phase_probs = {p: round(v / prob_sum, 4) for p, v in base_probs.items()}
        # Ensure exact sum to 1.0
        p_diff = round(1.0 - sum(norm_phase_probs.values()), 4)
        norm_phase_probs[active_phase] = round(norm_phase_probs[active_phase] + p_diff, 4)

        phase_pred = PhasePrediction(label=active_phase, probs=norm_phase_probs)

        # Generate tool probabilities based on phase correlation
        corr = PHASE_TOOL_CORRELATIONS.get(active_phase, {})
        tool_probs: dict[ToolId, float] = {}
        for tool in TOOL_ORDER:
            if tool in corr:
                p_tool = round(rng.uniform(corr[tool] - 0.15, min(1.0, corr[tool] + 0.15)), 4)
            else:
                p_tool = round(rng.uniform(0.01, 0.12), 4)
            tool_probs[tool] = max(0.0, min(1.0, p_tool))
            if tool_probs[tool] >= 0.50:
                tool_presence_counts[tool] += 1

        tools_pred = ToolPresencePrediction(probs=tool_probs)

        # Generate triplets (sporadic action events)
        triplet_preds: list[TripletPrediction] = []
        if rng.random() < 0.25:  # Triplet present in ~25% of seconds
            candidates = PHASE_TRIPLETS.get(active_phase, [])
            if candidates:
                ivt_id, ivt_name = rng.choice(candidates)
                score = round(rng.uniform(0.60, 0.96), 4)
                triplet_preds.append(
                    TripletPrediction(ivt_id=ivt_id, ivt_name=ivt_name, score=score)
                )

                if score > 0.90 and len(triplet_highlights) < 10:
                    triplet_highlights.append(
                        TripletHighlight(
                            ivt_id=ivt_id,
                            ivt_name=ivt_name,
                            t=t,
                            score=score,
                            phase=active_phase,
                        )
                    )

        rec = PerSecondRecord(
            schema_version=CONTRACT_VERSION,
            producer=producer,
            t=t,
            frame_idx=sec * 25,
            phase=phase_pred,
            tools=tools_pred,
            triplets=triplet_preds,
            quality_flags=[],
        )
        per_second_records.append(rec)

    # 4. Generate 5 Hz DetectionRecord stream (subsampled for speed: sample 100 random seconds)
    detection_records: list[DetectionRecord] = []
    # Sample bursts of detections
    sample_seconds = sorted(
        rng.sample(range(int(total_duration_s)), min(60, int(total_duration_s)))
    )
    for sec in sample_seconds:
        t_base = float(sec)
        active_p = per_second_records[sec].phase.label
        corr = PHASE_TOOL_CORRELATIONS.get(active_p, {})
        for sub_step in range(5):
            t_sub = round(t_base + sub_step * 0.2, 2)
            for tool, base_prob in corr.items():
                if rng.random() < base_prob:
                    # Realistic coordinates in standard 854x480 cropped frame
                    x1 = round(rng.uniform(100.0, 500.0), 1)
                    y1 = round(rng.uniform(80.0, 300.0), 1)
                    w = round(rng.uniform(60.0, 150.0), 1)
                    h = round(rng.uniform(60.0, 150.0), 1)
                    det = DetectionRecord(
                        schema_version=CONTRACT_VERSION,
                        producer=producer,
                        t=t_sub,
                        tool=tool,
                        bbox=[x1, y1, round(x1 + w, 1), round(y1 + h, 1)],
                        score=round(rng.uniform(0.65, 0.98), 4),
                        track_id=rng.randint(1, 12),
                    )
                    detection_records.append(det)

    # 5. Generate Tracks
    tracks: list[Track] = []
    for track_idx, tool in enumerate([ToolId.GRASPER, ToolId.HOOK, ToolId.CLIPPER], start=1):
        intervals: list[TimeInterval] = []
        # Create 2-3 intervals per track
        t_cur = round(total_duration_s * 0.1, 2)
        while t_cur < total_duration_s * 0.8:
            start_i = t_cur
            end_i = round(min(total_duration_s, start_i + rng.uniform(30.0, 180.0)), 2)
            intervals.append(TimeInterval(start=start_i, end=end_i))
            t_cur = round(end_i + rng.uniform(60.0, 300.0), 2)
        tracks.append(Track(track_id=track_idx, tool=tool, intervals=intervals))

    # 6. Aggregate tool usage
    tools_usage: list[ToolUsage] = []
    for tool in TOOL_ORDER:
        usage_s = float(tool_presence_counts[tool])
        pct = round(usage_s / total_duration_s * 100.0, 2) if total_duration_s > 0 else 0.0
        tools_usage.append(ToolUsage(tool=tool, usage_s=usage_s, pct=pct))

    # 7. Generate Key Events (P2 start, first clip in P3, cut, etc.)
    p2_seg = next(s for s in phase_segments if s.label == PhaseId.P2)
    p3_seg = next(s for s in phase_segments if s.label == PhaseId.P3)
    p4_seg = next(s for s in phase_segments if s.label == PhaseId.P4)
    p5_seg = next(s for s in phase_segments if s.label == PhaseId.P5)

    key_events = [
        KeyEvent(
            type="start_calot_dissection",
            t=p2_seg.start,
            conf=round(p2_seg.conf, 2),
            uncertain=p2_seg.uncertain,
            evidence=["phase_transition_P1_to_P2"],
        ),
        KeyEvent(
            type="first_clip",
            t=round(p3_seg.start + 12.0, 2),
            conf=0.91,
            uncertain=False,
            evidence=["clipper_presence", "triplet:clipper,clip,cystic_duct"],
        ),
        KeyEvent(
            type="cystic_duct_cut",
            t=round(p3_seg.start + 28.0, 2),
            conf=0.88,
            uncertain=False,
            evidence=["scissors_presence", "triplet:scissors,cut,cystic_duct"],
        ),
        KeyEvent(
            type="start_gallbladder_dissection",
            t=p4_seg.start,
            conf=round(p4_seg.conf, 2),
            uncertain=p4_seg.uncertain,
            evidence=["phase_transition_P3_to_P4"],
        ),
        KeyEvent(
            type="gallbladder_in_bag",
            t=round(p5_seg.start + 15.0, 2),
            conf=0.89,
            uncertain=False,
            evidence=["specimen_bag_presence"],
        ),
    ]

    # 8. Observed Deviations from reference cohort (P3 wording lexicon compliant)
    deviations: list[Deviation] = [
        Deviation(
            type="phase_duration",
            phase=PhaseId.P2,
            value_s=round(p2_seg.end - p2_seg.start, 2),
            cohort_p95_s=980.0,
            cohort_n=80,
            wording="Calot triangle dissection duration is within the observed range of the reference cohort (p95 = 980s).",
        )
    ]

    # 9. Video metadata
    video_meta = VideoMeta(
        fps=25.0,
        duration_s=total_duration_s,
        width=854,
        height=480,
        crop_offset=[42, 0, 770, 480],
        source=f"{video_id}.mp4",
        frame_count=int(total_duration_s * 25),
    )

    # 10. Complete Report
    report = Report(
        schema_version=CONTRACT_VERSION,
        producer=producer,
        video_id=video_id,
        dataset=dataset,
        duration_s=total_duration_s,
        status=ReportStatus.DRAFT_PENDING_REVIEW,
        disclaimer=RESEARCH_DISCLAIMER,
        phases=phase_segments,
        tools=tools_usage,
        events=key_events,
        deviations=deviations,
        triplet_highlights=triplet_highlights,
        confidence_notes=[
            "All phase boundaries calibrated using temperature scaling (T=1.15).",
            "Uncertainty threshold set at calibrated confidence < 0.50.",
        ],
        models={"M2_phase": "0.1.0", "M3_tools": "0.1.0-mock", "M4_triplets": "0.1.0-mock"},
    )

    return MockAnalysisResult(
        report=report,
        per_second_records=per_second_records,
        detection_records=detection_records,
        tracks=tracks,
        video_meta=video_meta,
    )
