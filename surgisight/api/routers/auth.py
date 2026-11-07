"""Authentication endpoints for SurgiSight.

Provides:
- POST /auth/login with sliding window rate limiting
- POST /auth/refresh
- GET /auth/me
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from surgisight.api.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    login_rate_limiter,
    verify_password,
)
from surgisight.api.deps import get_current_user
from surgisight.db import UserModel, get_db
from surgisight.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, description="User email address")
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: str
    email: str
    role: str
    is_active: bool
    created_at: str


@router.post("/login", response_model=TokenResponse)
def login(
    req: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    """Authenticate user with email and password, issuing access and refresh tokens."""
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"{client_ip}:{req.email.lower()}"

    if login_rate_limiter.is_rate_limited(rate_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again later.",
        )

    user = db.execute(
        select(UserModel).where(UserModel.email == req.email.lower())
    ).scalar_one_or_none()
    if user is None or not verify_password(req.password, user.password_hash):
        login_rate_limiter.record_attempt(rate_key, success=False)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    # Success: reset rate limit tracking for this user
    login_rate_limiter.record_attempt(rate_key, success=True)

    access_token = create_access_token(user_id=user.id, role=user.role)
    refresh_token = create_refresh_token(user_id=user.id)

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        max_age=settings.jwt_refresh_expire_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path="/auth/refresh",
    )
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.jwt_access_expire_minutes * 60,
    )


@router.post("/refresh", response_model=RefreshResponse)
def refresh(
    db: Annotated[Session, Depends(get_db)],
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> RefreshResponse:
    """Issue a new access token using the HttpOnly refresh cookie."""
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh cookie.")
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(err),
        ) from err

    user_id = payload.get("sub")
    user = db.execute(select(UserModel).where(UserModel.id == user_id)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    access_token = create_access_token(user_id=user.id, role=user.role)
    return RefreshResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.jwt_access_expire_minutes * 60,
    )


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    """Clear the HttpOnly refresh cookie from the browser."""
    response.delete_cookie(
        key="refresh_token",
        path="/auth/refresh",
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
    )
    return {"status": "signed_out"}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: Annotated[UserModel, Depends(get_current_user)]) -> UserResponse:
    """Return profile of currently authenticated user."""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        role=current_user.role,
        is_active=current_user.is_active,
        created_at=current_user.created_at.isoformat(),
    )
