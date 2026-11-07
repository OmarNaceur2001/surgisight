"""Wording lexicon validator enforcing Principle P3: 'Describe, never judge'."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

LEXICON_PATH = Path("docs/wording_lexicon.yaml")


def load_forbidden_words(lexicon_file: Path | None = None) -> list[str]:
    """Load list of forbidden evaluative terms from wording_lexicon.yaml."""
    path = lexicon_file or LEXICON_PATH
    if not path.is_file():
        # Fallback default list if file not yet written or in alternate working dir
        return [
            "error",
            "errors",
            "mistake",
            "mistakes",
            "bad",
            "poor",
            "poorly",
            "wrong",
            "fault",
            "faulty",
            "failure",
            "failures",
            "complication",
            "complications",
            "competent",
            "incompetent",
            "skilled",
            "unskilled",
            "clumsy",
            "negligent",
            "grade",
        ]
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [str(w).lower() for w in data.get("forbidden_words", [])]


def find_forbidden_words(text: str, forbidden_words: list[str] | None = None) -> list[str]:
    """Scan text for any forbidden evaluative words (case-insensitive word boundary match)."""
    words = forbidden_words if forbidden_words is not None else load_forbidden_words()
    found: list[str] = []
    for word in words:
        # Match whole words only
        pattern = rf"\b{re.escape(word)}\b"
        if re.search(pattern, text, flags=re.IGNORECASE):
            found.append(word)
    return found


def validate_text_lexicon(text: str, context: str = "text") -> None:
    """Raise ValueError if text contains any forbidden word under Principle P3."""
    violations = find_forbidden_words(text)
    if violations:
        raise ValueError(
            f"Principle P3 violation in {context}: text contains forbidden evaluative term(s): {violations}. "
            "SurgiSight must describe observations neutrally, never judge."
        )


def validate_object_lexicon(obj: Any, path: str = "root") -> None:
    """Recursively validate all string values in a dictionary/list/model."""
    if isinstance(obj, str):
        validate_text_lexicon(obj, context=path)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            validate_object_lexicon(v, path=f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, item in enumerate(obj):
            validate_object_lexicon(item, path=f"{path}[{i}]")
