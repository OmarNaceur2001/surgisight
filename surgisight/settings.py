"""Application settings loaded from environment / .env file.

All settings are read once at import time via pydantic-settings.
Never mutate settings at runtime.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """SurgiSight runtime configuration."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./surgisight_dev.db"

    # ------------------------------------------------------------------
    # CORS — explicit list, never wildcard (P7)
    # ------------------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        """Return parsed, stripped, non-empty CORS origins."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @field_validator("cors_origins")
    @classmethod
    def no_wildcard(cls, v: str) -> str:
        if "*" in v:
            raise ValueError("CORS origins must not contain '*' (security: P7)")
        return v

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    jwt_secret: str = "CHANGE_ME_IN_PRODUCTION_USE_32_BYTE_RANDOM_SECRET"
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 7
    refresh_cookie_secure: bool = False  # Set true whenever the API is served over HTTPS.

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------
    storage_dir: str = "storage"
    max_upload_size_mb: int = 2048  # 2 GB cap per upload

    # ------------------------------------------------------------------
    # Feature flags
    # ------------------------------------------------------------------
    use_real_m2: bool = False
    use_real_m3: bool = False
    use_real_m4: bool = False

    # Test-only: allow artifacts whose name contains 'synthetic'
    allow_synthetic_artifact: bool = False

    # ------------------------------------------------------------------
    # Login rate limiting
    # ------------------------------------------------------------------
    login_max_attempts: int = 10
    login_window_seconds: int = 300

    @model_validator(mode="after")
    def warn_default_secret(self) -> Settings:
        import warnings

        if self.jwt_secret == "CHANGE_ME_IN_PRODUCTION_USE_32_BYTE_RANDOM_SECRET":
            warnings.warn(
                "JWT_SECRET is using the default value. Set a secure random secret in .env.",
                UserWarning,
                stacklevel=2,
            )
        return self


# Singleton — import this everywhere
settings = Settings()
