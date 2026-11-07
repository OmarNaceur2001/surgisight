"""Authentication and cryptography services for SurgiSight.

Security features (P7):
- Password hashing with modern Argon2id via pwdlib[argon2]
- Cryptographic JWT access tokens (short-lived) and refresh tokens (long-lived) via PyJWT
- Strict algorithm pinning to prevent algorithm-confusion attacks (e.g. none or RS256/HMAC)
- In-memory sliding window rate limiter against brute-force login attempts
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from surgisight.settings import settings

# Argon2id password hasher
_password_hasher = PasswordHash.recommended()


def hash_password(plain_password: str) -> str:
    """Hash plaintext password using Argon2id."""
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plaintext password against stored Argon2id hash."""
    return _password_hasher.verify(plain_password, hashed_password)


def create_access_token(
    user_id: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Issue a signed JWT access token."""
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.jwt_access_expire_minutes)
    )
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    user_id: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Issue a signed JWT refresh token."""
    expire = datetime.now(UTC) + (expires_delta or timedelta(days=settings.jwt_refresh_expire_days))
    payload: dict[str, Any] = {
        "sub": user_id,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    """Decode and validate token signature, expiration, and token type.

    Strictly pins algorithm to HS256 to mitigate algorithm confusion attacks.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as err:
        raise ValueError("Token has expired") from err
    except jwt.InvalidTokenError as err:
        raise ValueError(f"Invalid token: {err}") from err

    if payload.get("type") != expected_type:
        raise ValueError(
            f"Invalid token type: expected '{expected_type}', got '{payload.get('type')}'"
        )

    return payload


class LoginRateLimiter:
    """In-memory sliding window rate limiter for login attempts."""

    def __init__(self, max_attempts: int | None = None, window_seconds: int | None = None) -> None:
        self.max_attempts = max_attempts or settings.login_max_attempts
        self.window_seconds = window_seconds or settings.login_window_seconds
        # key -> list of attempt timestamps (monotonic)
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def is_rate_limited(self, key: str) -> bool:
        """Return True if key has exceeded allowed login attempts within window."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        # Evict old attempts
        recent = [t for t in self._attempts[key] if t > cutoff]
        self._attempts[key] = recent
        return len(recent) >= self.max_attempts

    def record_attempt(self, key: str, success: bool) -> None:
        """Record attempt. If successful, clear failed attempt history."""
        if success:
            self._attempts.pop(key, None)
        else:
            self._attempts[key].append(time.monotonic())

    def reset(self) -> None:
        """Clear all rate limit state (useful in tests)."""
        self._attempts.clear()


# Global rate limiter instance
login_rate_limiter = LoginRateLimiter()
