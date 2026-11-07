"""Provider interfaces and mock implementations for SurgiSight pipeline stages.

Architecture:
- Clear decoupled provider interfaces (Phase, Tool Presence, Detector, Tracker, Triplet)
- Feature-flagged provider registry allowing real models (WP6) to substitute mocks
- Contract validation on every provider output
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from surgisight.contract.mock_generator import generate_mock_analysis
from surgisight.contract.models import (
    DetectionRecord,
    PhasePrediction,
    PhaseSegment,
    ToolPresencePrediction,
    Track,
    TripletPrediction,
)
from surgisight.settings import settings


@runtime_checkable
class PhaseProvider(Protocol):
    """Generates phase predictions and segment boundaries."""

    def predict_phases(
        self,
        duration_s: float,
        seed: int = 42,
    ) -> tuple[list[PhasePrediction], list[PhaseSegment]]: ...


@runtime_checkable
class ToolPresenceProvider(Protocol):
    """Generates 1 Hz instrument presence predictions across 7 tools."""

    def predict_tools(
        self,
        duration_s: float,
        phases: list[PhasePrediction],
        seed: int = 42,
    ) -> list[ToolPresencePrediction]: ...


@runtime_checkable
class DetectorProvider(Protocol):
    """Generates 5 Hz spatial bounding boxes for instruments."""

    def detect(
        self,
        duration_s: float,
        phases: list[PhasePrediction],
        seed: int = 42,
    ) -> list[DetectionRecord]: ...


@runtime_checkable
class TrackerProvider(Protocol):
    """Links detections into temporal tracks."""

    def track(
        self,
        detections: list[DetectionRecord],
        duration_s: float,
    ) -> list[Track]: ...


@runtime_checkable
class TripletProvider(Protocol):
    """Generates action triplet predictions <instrument, verb, target>."""

    def predict_triplets(
        self,
        duration_s: float,
        phases: list[PhasePrediction],
        seed: int = 42,
    ) -> list[list[TripletPrediction]]: ...


# ==============================================================================
# Mock Provider Implementations (from Data Contract mock generator)
# ==============================================================================


class MockPhaseProvider:
    """Mock implementation returning physiologically plausible surgical phases."""

    def predict_phases(
        self,
        duration_s: float,
        seed: int = 42,
    ) -> tuple[list[PhasePrediction], list[PhaseSegment]]:
        duration_min = max(1.0, duration_s / 60.0)
        res = generate_mock_analysis(duration_minutes=duration_min, seed=seed)
        preds = [r.phase for r in res.per_second_records]
        return preds, res.report.phases


class MockToolPresenceProvider:
    """Mock implementation returning phase-correlated tool presence probabilities."""

    def predict_tools(
        self,
        duration_s: float,
        phases: list[PhasePrediction],
        seed: int = 42,
    ) -> list[ToolPresencePrediction]:
        duration_min = max(1.0, duration_s / 60.0)
        res = generate_mock_analysis(duration_minutes=duration_min, seed=seed)
        return [r.tools for r in res.per_second_records]


class MockDetectorProvider:
    """Mock implementation returning 5 Hz tool bounding box detections."""

    def detect(
        self,
        duration_s: float,
        phases: list[PhasePrediction],
        seed: int = 42,
    ) -> list[DetectionRecord]:
        duration_min = max(1.0, duration_s / 60.0)
        res = generate_mock_analysis(duration_minutes=duration_min, seed=seed)
        return res.detection_records


class MockTrackerProvider:
    """Mock implementation returning multi-interval tool trajectories."""

    def track(
        self,
        detections: list[DetectionRecord],
        duration_s: float,
    ) -> list[Track]:
        duration_min = max(1.0, duration_s / 60.0)
        res = generate_mock_analysis(duration_minutes=duration_min, seed=42)
        return res.tracks


class MockTripletProvider:
    """Mock implementation returning surgical action triplets."""

    def predict_triplets(
        self,
        duration_s: float,
        phases: list[PhasePrediction],
        seed: int = 42,
    ) -> list[list[TripletPrediction]]:
        duration_min = max(1.0, duration_s / 60.0)
        res = generate_mock_analysis(duration_minutes=duration_min, seed=seed)
        return [r.triplets for r in res.per_second_records]


# ==============================================================================
# Provider Registry
# ==============================================================================


class ProviderRegistry:
    """Central registry resolving real model providers vs fallback mock providers."""

    @classmethod
    def get_phase_provider(cls) -> PhaseProvider:
        if settings.use_real_m2:
            try:
                from surgisight.models.m2_phase.real_provider import RealPhaseProvider

                return RealPhaseProvider()
            except ImportError:
                pass
        return MockPhaseProvider()

    @classmethod
    def get_tool_provider(cls) -> ToolPresenceProvider:
        return MockToolPresenceProvider()

    @classmethod
    def get_detector_provider(cls) -> DetectorProvider:
        return MockDetectorProvider()

    @classmethod
    def get_tracker_provider(cls) -> TrackerProvider:
        return MockTrackerProvider()

    @classmethod
    def get_triplet_provider(cls) -> TripletProvider:
        return MockTripletProvider()
