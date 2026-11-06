"""Shared pytest fixtures for SurgiSight tests."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Use asyncio backend for anyio-based tests."""
    return "asyncio"
