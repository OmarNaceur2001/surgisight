"""FastAPI dependencies for authentication, role authorization, and audit logging.

Enforces:
- Role permissions: admin, reviewer, researcher, viewer (P7)
- Inactive user blocking
- Audit logging of video and report accesses (P7)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from surgisight.api.auth import decode_token
from surgisight.contract.types import UserRole
from surgisight.db import AccessLogModel, UserModel, get_db

security_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> UserModel:
    """Validate Bearer token and return active UserModel."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(err),
            headers={"WWW-Authenticate": "Bearer"},
        ) from err

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload missing subject identifier",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.execute(select(UserModel).where(UserModel.id == user_id)).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )

    return user


def require_roles(*allowed_roles: str | UserRole) -> Callable[[UserModel], UserModel]:
    """Dependency factory checking that current user possesses an authorized role."""
    roles_set = {str(r.value if isinstance(r, UserRole) else r) for r in allowed_roles}
    # Admin always holds permissions for reviewer/researcher/viewer actions
    roles_set.add(UserRole.ADMIN.value)

    def role_checker(current_user: Annotated[UserModel, Depends(get_current_user)]) -> UserModel:
        if current_user.role not in roles_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires one of roles: {sorted(roles_set)}. Current role: '{current_user.role}'.",
            )
        return current_user

    return role_checker


def record_access_log(
    db: Session,
    action: str,
    user_id: str | None = None,
    video_id: str | None = None,
) -> AccessLogModel:
    """Create and persist an access log audit entry (P7)."""
    entry = AccessLogModel(
        user_id=user_id,
        video_id=video_id,
        action=action,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
