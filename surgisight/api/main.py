"""SurgiSight FastAPI application.

Research prototype — not for clinical use.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

from surgisight.api.deps import record_access_log, require_roles
from surgisight.api.routers import auth, media, videos
from surgisight.api.routers.analyses import create_router as analyses_create_router
from surgisight.api.routers.analyses import router as analyses_router
from surgisight.api.routers.cohort import router as cohort_router
from surgisight.api.routers.library import router as library_router
from surgisight.api.routers.observability import router as observability_router
from surgisight.api.routers.reports import router as reports_router
from surgisight.api.routers.ws import router as websocket_router
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

for route in (
    auth.router,
    videos.router,
    library_router,
    analyses_create_router,
    analyses_router,
    reports_router,
    cohort_router,
    observability_router,
    media.router,
):
    app.include_router(route)
app.include_router(websocket_router)


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    """Basic liveness probe with mandatory research notice."""
    return {"status": "ok", "banner": "Research prototype — not for clinical use", "version": "0.1.0"}


@app.get("/health/db", tags=["ops"])
async def health_db() -> dict[str, str]:
    """Check configured database connectivity."""
    engine = create_async_engine(settings.database_url, echo=False)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "reachable"}
    except Exception:
        return {"status": "degraded", "database": "unreachable"}
    finally:
        await engine.dispose()


@app.get("/test/reviewer-only", tags=["test"])
def test_reviewer_endpoint(
    user: Annotated[UserModel, Depends(require_roles(UserRole.REVIEWER))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    """Protected route used by the role matrix tests."""
    record_access_log(db, action="review_access", user_id=user.id)
    return {"message": "reviewed_granted", "user": user.email}


@app.get("/test/researcher-only", tags=["test"])
def test_researcher_endpoint(
    user: Annotated[UserModel, Depends(require_roles(UserRole.RESEARCHER, UserRole.REVIEWER))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    """Protected route used by the role matrix tests."""
    record_access_log(db, action="research_access", user_id=user.id)
    return {"message": "research_granted", "user": user.email}


@app.get("/test/viewer-only", tags=["test"])
def test_viewer_endpoint(
    user: Annotated[UserModel, Depends(require_roles(UserRole.VIEWER, UserRole.RESEARCHER, UserRole.REVIEWER))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    """Protected route used by the role matrix tests."""
    record_access_log(db, action="view_access", user_id=user.id)
    return {"message": "view_granted", "user": user.email}
