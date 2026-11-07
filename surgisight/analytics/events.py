"""Surgical event detection and conflict precedence resolution."""

from __future__ import annotations

from surgisight.analytics.lexicon import validate_text_lexicon
from surgisight.contract.models import (
    KeyEvent,
    PhasePrediction,
    PhaseSegment,
    ToolPresencePrediction,
)
from surgisight.contract.types import PHASE_NAMES, PhaseId, ToolId


def detect_surgical_events(
    phase_predictions: list[PhasePrediction],
    tool_predictions: list[ToolPresencePrediction],
    phase_segments: list[PhaseSegment] | None = None,
) -> list[KeyEvent]:
    """Detect key surgical milestones from 1 Hz phase and tool presence streams.

    Applies non-negotiable principle P5: Conflicting signals between phase classification
    and tool presence are NEVER silently resolved; they are surfaced as events flagged
    `uncertain=True` with explicit diagnostic evidence notes.
    """
    events: list[KeyEvent] = []
    num_steps = min(len(phase_predictions), len(tool_predictions))
    if num_steps == 0:
        return []

    # 1. Calot Dissection Start (Primary milestone: P2 entry or early Calot dissection tools)
    p2_start_t: float | None = None
    for s in range(num_steps):
        if phase_predictions[s].label == PhaseId.P2:
            p2_start_t = float(s)
            conf = phase_predictions[s].confidence
            uncertain = conf < 0.50
            evidence = [
                f"Phase P2 entry observed at t={p2_start_t:.1f}s",
                f"Phase confidence: {conf:.2f}",
            ]
            for ev in evidence:
                validate_text_lexicon(ev, context="calot_dissection_start evidence")
            events.append(
                KeyEvent(
                    type="calot_dissection_start",
                    t=round(p2_start_t, 2),
                    conf=round(conf, 4),
                    uncertain=uncertain,
                    evidence=evidence,
                )
            )
            break

    # 2. First Clip (Primary milestone: Clipper presence >= 0.50)
    first_clip_t: float | None = None
    for s in range(num_steps):
        clipper_prob = tool_predictions[s].probs.get(ToolId.CLIPPER, 0.0)
        if clipper_prob >= 0.50:
            first_clip_t = float(s)
            curr_phase = phase_predictions[s].label
            conf = clipper_prob

            # Check for conflict: Clipper active outside P3 (e.g. during P2)
            if curr_phase != PhaseId.P3:
                uncertain = True
                conf = min(conf, 0.45)  # Penalize confidence due to phase contradiction
                evidence = [
                    f"Clipper presence detected (p={clipper_prob:.2f}) at t={first_clip_t:.1f}s",
                    f"Phase classification at this timestamp indicates {curr_phase.value} ({PHASE_NAMES[curr_phase]})",
                    "Discrepancy flagged for human review",
                ]
            else:
                uncertain = conf < 0.50
                evidence = [
                    f"Clipper presence detected (p={clipper_prob:.2f}) in canonical clipping phase P3",
                    f"Phase confidence: {phase_predictions[s].confidence:.2f}",
                ]

            for ev in evidence:
                validate_text_lexicon(ev, context="first_clip evidence")

            events.append(
                KeyEvent(
                    type="first_clip",
                    t=round(first_clip_t, 2),
                    conf=round(conf, 4),
                    uncertain=uncertain,
                    evidence=evidence,
                )
            )
            break

    # 3. Cystic Duct Cut (Scissors active after first clip or in P3)
    start_search_t = int(first_clip_t) if first_clip_t is not None else 0
    for s in range(start_search_t, num_steps):
        scissors_prob = tool_predictions[s].probs.get(ToolId.SCISSORS, 0.0)
        if scissors_prob >= 0.50:
            t = float(s)
            curr_phase = phase_predictions[s].label
            conf = scissors_prob
            uncertain = conf < 0.50 or curr_phase != PhaseId.P3
            evidence = [
                f"Scissors presence detected (p={scissors_prob:.2f}) at t={t:.1f}s",
                f"Phase at timestamp: {curr_phase.value} ({PHASE_NAMES[curr_phase]})",
            ]
            for ev in evidence:
                validate_text_lexicon(ev, context="cystic_duct_cut evidence")
            events.append(
                KeyEvent(
                    type="cystic_duct_cut",
                    t=round(t, 2),
                    conf=round(conf, 4),
                    uncertain=uncertain,
                    evidence=evidence,
                )
            )
            break

    # 4. Gallbladder Dissection Start (Transition into P4)
    for s in range(num_steps):
        if phase_predictions[s].label == PhaseId.P4:
            t = float(s)
            conf = phase_predictions[s].confidence
            uncertain = conf < 0.50
            evidence = [
                f"Transition into phase P4 ({PHASE_NAMES[PhaseId.P4]}) observed at t={t:.1f}s",
                f"Phase confidence: {conf:.2f}",
            ]
            for ev in evidence:
                validate_text_lexicon(ev, context="gallbladder_dissection_start evidence")
            events.append(
                KeyEvent(
                    type="gallbladder_dissection_start",
                    t=round(t, 2),
                    conf=round(conf, 4),
                    uncertain=uncertain,
                    evidence=evidence,
                )
            )
            break

    # 5. Gallbladder in Bag (SpecimenBag presence >= 0.50)
    for s in range(num_steps):
        bag_prob = tool_predictions[s].probs.get(ToolId.SPECIMEN_BAG, 0.0)
        if bag_prob >= 0.50:
            t = float(s)
            curr_phase = phase_predictions[s].label
            conf = bag_prob
            # Canonical in P5 or P6
            is_canonical = curr_phase in (PhaseId.P5, PhaseId.P6)
            uncertain = conf < 0.50 or not is_canonical
            evidence = [
                f"SpecimenBag presence detected (p={bag_prob:.2f}) at t={t:.1f}s",
                f"Phase at timestamp: {curr_phase.value} ({PHASE_NAMES[curr_phase]})",
            ]
            for ev in evidence:
                validate_text_lexicon(ev, context="gallbladder_in_bag evidence")
            events.append(
                KeyEvent(
                    type="gallbladder_in_bag",
                    t=round(t, 2),
                    conf=round(conf, 4),
                    uncertain=uncertain,
                    evidence=evidence,
                )
            )
            break

    # 6. Gallbladder Retraction (Transition into P7)
    for s in range(num_steps):
        if phase_predictions[s].label == PhaseId.P7:
            t = float(s)
            conf = phase_predictions[s].confidence
            uncertain = conf < 0.50
            evidence = [
                f"Phase P7 entry observed at t={t:.1f}s",
                f"Phase confidence: {conf:.2f}",
            ]
            for ev in evidence:
                validate_text_lexicon(ev, context="gallbladder_retraction evidence")
            events.append(
                KeyEvent(
                    type="gallbladder_retraction",
                    t=round(t, 2),
                    conf=round(conf, 4),
                    uncertain=uncertain,
                    evidence=evidence,
                )
            )
            break

    return events
