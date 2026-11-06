"""Smoke tests — verify basic imports and settings load correctly."""

from __future__ import annotations


def test_package_importable() -> None:
    import surgisight  # noqa: F401

    assert surgisight.__version__ == "0.1.0"


def test_settings_load() -> None:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        from surgisight.settings import settings

    assert settings.cors_origins_list  # non-empty list
    assert "*" not in settings.cors_origins_list  # never wildcard


def test_app_importable() -> None:
    from surgisight.api.main import app

    assert app.title == "SurgiSight API"


def test_health_endpoint() -> None:
    from fastapi.testclient import TestClient

    from surgisight.api.main import app

    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "not for clinical use" in data["banner"].lower()
