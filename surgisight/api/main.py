"""FastAPI application entry point.

Research prototype — not for clinical use.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from surgisight.settings import settings

app = FastAPI(
    title="SurgiSight API",
    description="AI surgical video copilot — **Research prototype, not for clinical use**.",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS — explicit origins only, never wildcard (P7)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Basic liveness probe. Returns the research-use-only banner."""
    return {
        "status": "ok",
        "banner": "Research prototype — not for clinical use",
        "version": "0.1.0",
    }


@app.get("/health/db", tags=["ops"])
async def health_db() -> dict[str, str]:
    """Database connectivity probe."""
    try:
        # Lazy import to avoid loading DB on simple health checks
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(settings.database_url, echo=False)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return {"status": "ok", "database": "reachable"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "database": "unreachable", "detail": str(exc)}
