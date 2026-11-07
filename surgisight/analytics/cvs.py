"""Optional Critical View of Safety interface and neutral mock (Stage 2 stub)."""
from __future__ import annotations

from typing import Protocol


class CVSProvider(Protocol):
    """Interface for a future evidence-grounded CVS assessment provider."""

    def assess(self, evidence_refs: list[str]) -> dict[str, object]:
        """Return an explicit assessment state from supplied evidence references."""
        ...


class MockCVSProvider:
    """Non-assessing placeholder; it does not infer or grade CVS."""

    def assess(self, evidence_refs: list[str]) -> dict[str, object]:
        """Return not_assessed without implying a positive or negative finding."""
        return {
            "status": "not_assessed",
            "provider": "mock",
            "evidence_refs": list(evidence_refs),
            "note": "CVS assessment is an optional future research interface.",
        }
