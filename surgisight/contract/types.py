"""Type definitions and enumerations for SurgiSight Data Contract v1.0.

Research prototype -- not for clinical use.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

CONTRACT_VERSION = "1.0"
RESEARCH_DISCLAIMER = "Research prototype — not for clinical use"


class PhaseId(StrEnum):
    """Surgical phases for laparoscopic cholecystectomy (P1..P7)."""

    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"
    P5 = "P5"
    P6 = "P6"
    P7 = "P7"


PHASE_NAMES: dict[PhaseId, str] = {
    PhaseId.P1: "Preparation",
    PhaseId.P2: "Calot triangle dissection",
    PhaseId.P3: "Clipping and cutting",
    PhaseId.P4: "Gallbladder dissection",
    PhaseId.P5: "Gallbladder packaging",
    PhaseId.P6: "Cleaning and coagulation",
    PhaseId.P7: "Gallbladder retraction",
}

# Ordered list of phase IDs
PHASE_ORDER: list[PhaseId] = [
    PhaseId.P1,
    PhaseId.P2,
    PhaseId.P3,
    PhaseId.P4,
    PhaseId.P5,
    PhaseId.P6,
    PhaseId.P7,
]


class ToolId(StrEnum):
    """Seven surgical instruments tracked in cholecystectomy."""

    GRASPER = "Grasper"
    BIPOLAR = "Bipolar"
    HOOK = "Hook"
    SCISSORS = "Scissors"
    CLIPPER = "Clipper"
    IRRIGATOR = "Irrigator"
    SPECIMEN_BAG = "SpecimenBag"


TOOL_ORDER: list[ToolId] = [
    ToolId.GRASPER,
    ToolId.BIPOLAR,
    ToolId.HOOK,
    ToolId.SCISSORS,
    ToolId.CLIPPER,
    ToolId.IRRIGATOR,
    ToolId.SPECIMEN_BAG,
]


class ReportStatus(StrEnum):
    """Operative report review status."""

    DRAFT_PENDING_REVIEW = "DRAFT_PENDING_REVIEW"
    REVIEWED = "REVIEWED"


class RunStatus(StrEnum):
    """Analysis run status in pipeline."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class UserRole(StrEnum):
    """User access control roles."""

    ADMIN = "admin"
    REVIEWER = "reviewer"
    RESEARCHER = "researcher"
    VIEWER = "viewer"


class TargetType(StrEnum):
    """Correction target entity types."""

    PHASE_BOUNDARY = "PHASE_BOUNDARY"
    PHASE_LABEL = "PHASE_LABEL"
    KEY_EVENT = "KEY_EVENT"
    TOOL_INTERVAL = "TOOL_INTERVAL"
    METRIC = "METRIC"
    REPORT_NOTE = "REPORT_NOTE"


QualityFlag = Literal[
    "normal",
    "motion_blur",
    "smoke",
    "blood_on_lens",
    "underexposed",
    "overexposed",
    "out_of_body",
]
