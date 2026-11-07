"""FastAPI application entry point.

Research prototype — not for clinical use.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from surgisight.api.deps import record_access_log, require_roles
from surgisight.api.routers import analyses, auth, media, videos
from surgisight.contract.types import UserRole
from surgisight.db import UserModel, get_db
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

# Mount Routers
app.include_router(auth.router)
app.include_router(videos.router)
app.include_router(media.router)
app.include_router(analyses.router)


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
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(settings.database_url, echo=False)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return {"status": "ok", "database": "reachable"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "database": "unreachable", "detail": str(exc)}


# Protected route stubs for role matrix verification and audit logging (P6, P7)
@app.get("/test/reviewer-only", tags=["test"])
def test_reviewer_endpoint(
    user: Annotated[UserModel, Depends(require_roles(UserRole.REVIEWER))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    record_access_log(db, action="review_access", user_id=user.id)
    return {"message": "reviewed_granted", "user": user.email}


@app.get("/test/researcher-only", tags=["test"])
def test_researcher_endpoint(
    user: Annotated[UserModel, Depends(require_roles(UserRole.RESEARCHER, UserRole.REVIEWER))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    record_access_log(db, action="research_access", user_id=user.id)
    return {"message": "research_granted", "user": user.email}


@app.get("/test/viewer-only", tags=["test"])
def test_viewer_endpoint(
    user: Annotated[
        UserModel, Depends(require_roles(UserRole.VIEWER, UserRole.RESEARCHER, UserRole.REVIEWER))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    record_access_log(db, action="view_access", user_id=user.id)
    return {"message": "view_granted", "user": user.email}
