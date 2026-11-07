"""Tests for SurgiSight Authentication, Authorization, and Audit Logging (WP3).

Covers:
- Password hashing & verification with Argon2id
- JWT token lifecycle (access, refresh)
- Tampered token, expired token, and algorithm confusion attack rejection
- Login rate limiting (sliding window brute-force protection)
- User creation CLI
- Role Matrix test: (every role x every protected endpoint)
- Access log creation (P7 audit requirement)
"""

from __future__ import annotations

import time
from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from surgisight.api.auth import (
    LoginRateLimiter,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    login_rate_limiter,
    verify_password,
)
from surgisight.api.main import app
from surgisight.contract.types import UserRole
from surgisight.db import AccessLogModel, UserModel, get_db, init_db
from surgisight.settings import settings


@pytest.fixture
def auth_db():
    """In-memory SQLite database for authentication testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        engine.dispose()


@pytest.fixture
def client(auth_db: Session) -> TestClient:
    """FastAPI TestClient with overridden get_db dependency."""

    def override_get_db():
        try:
            yield auth_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


# ==============================================================================
# 1. Password Hashing (Argon2id)
# ==============================================================================


def test_password_hashing() -> None:
    raw_pwd = "CorrectSurgicalPassword#2026"
    pwd_hash = hash_password(raw_pwd)

    assert pwd_hash.startswith("$argon2id$")
    assert verify_password(raw_pwd, pwd_hash) is True
    assert verify_password("WrongPassword", pwd_hash) is False
    assert verify_password("", pwd_hash) is False


# ==============================================================================
# 2. JWT Lifecycle & Security Checks
# ==============================================================================


def test_access_token_creation_and_decoding() -> None:
    token = create_access_token(user_id="user_123", role="reviewer")
    payload = decode_token(token, expected_type="access")

    assert payload["sub"] == "user_123"
    assert payload["role"] == "reviewer"
    assert payload["type"] == "access"


def test_refresh_token_creation_and_decoding() -> None:
    token = create_refresh_token(user_id="user_123")
    payload = decode_token(token, expected_type="refresh")

    assert payload["sub"] == "user_123"
    assert payload["type"] == "refresh"


def test_token_type_mismatch_rejected() -> None:
    access_token = create_access_token(user_id="u1", role="admin")
    refresh_token = create_refresh_token(user_id="u1")

    # Using access token where refresh token is required
    with pytest.raises(ValueError, match="Invalid token type: expected 'refresh'"):
        decode_token(access_token, expected_type="refresh")

    # Using refresh token where access token is required
    with pytest.raises(ValueError, match="Invalid token type: expected 'access'"):
        decode_token(refresh_token, expected_type="access")


def test_expired_token_rejected() -> None:
    expired_token = create_access_token(
        user_id="u_exp", role="viewer", expires_delta=timedelta(seconds=-10)
    )
    with pytest.raises(ValueError, match="Token has expired"):
        decode_token(expired_token, expected_type="access")


def test_tampered_token_rejected() -> None:
    token = create_access_token(user_id="u1", role="viewer")
    # Tamper with the signature portion
    tampered = token[:-6] + "xxxxxx"
    with pytest.raises(ValueError, match="Invalid token"):
        decode_token(tampered, expected_type="access")


def test_algorithm_confusion_attack_rejected() -> None:
    """Tokens signed with 'none' or mismatched algorithms must be rejected."""
    # 1. None algorithm attack
    none_payload = {
        "sub": "attacker",
        "role": "admin",
        "type": "access",
        "exp": int(time.time()) + 3600,
    }
    none_token = jwt.encode(none_payload, key="", algorithm="none")

    with pytest.raises(ValueError):
        decode_token(none_token, expected_type="access")

    # 2. Symmetric key with wrong algorithm header
    wrong_alg_token = jwt.encode(none_payload, settings.jwt_secret, algorithm="HS384")
    with pytest.raises(ValueError):
        decode_token(wrong_alg_token, expected_type="access")


# ==============================================================================
# 3. Rate Limiter
# ==============================================================================


def test_login_rate_limiter() -> None:
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60)
    ip_key = "192.168.1.100:test@doc.org"

    assert limiter.is_rate_limited(ip_key) is False

    limiter.record_attempt(ip_key, success=False)
    limiter.record_attempt(ip_key, success=False)
    assert limiter.is_rate_limited(ip_key) is False

    limiter.record_attempt(ip_key, success=False)
    # 3rd failure hits limit
    assert limiter.is_rate_limited(ip_key) is True

    # Success resets history
    limiter.record_attempt(ip_key, success=True)
    assert limiter.is_rate_limited(ip_key) is False


# ==============================================================================
# 4. Auth Endpoints: /auth/login, /auth/refresh, /auth/me
# ==============================================================================


def test_login_success_and_refresh_flow(client: TestClient, auth_db: Session) -> None:
    login_rate_limiter.reset()

    user = UserModel(
        email="surgeon@surgisight.edu",
        password_hash=hash_password("SafeSurgery123!"),
        role="reviewer",
        is_active=True,
    )
    auth_db.add(user)
    auth_db.commit()

    # 1. Login
    login_res = client.post(
        "/auth/login",
        json={"email": "surgeon@surgisight.edu", "password": "SafeSurgery123!"},
    )
    assert login_res.status_code == 200
    data = login_res.json()
    assert "access_token" in data
    assert "refresh_token" not in data
    assert "refresh_token" in login_res.cookies
    assert "httponly" in login_res.headers.get("set-cookie", "").lower()
    assert data["token_type"] == "bearer"

    access_token = data["access_token"]

    # 2. Get profile /auth/me
    me_res = client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["email"] == "surgeon@surgisight.edu"
    assert me_data["role"] == "reviewer"

    # 3. Refresh access token
    ref_res = client.post("/auth/refresh")
    assert ref_res.status_code == 200
    ref_data = ref_res.json()
    assert "access_token" in ref_data
    ref_payload = decode_token(ref_data["access_token"], expected_type="access")
    assert ref_payload["sub"] == user.id
    assert ref_payload["role"] == "reviewer"


def test_login_invalid_password(client: TestClient, auth_db: Session) -> None:
    login_rate_limiter.reset()

    user = UserModel(
        email="doctor@test.org",
        password_hash=hash_password("ValidPassword"),
        role="viewer",
    )
    auth_db.add(user)
    auth_db.commit()

    res = client.post("/auth/login", json={"email": "doctor@test.org", "password": "WrongPassword"})
    assert res.status_code == 401
    assert "Incorrect email or password" in res.json()["detail"]


def test_login_deactivated_account(client: TestClient, auth_db: Session) -> None:
    login_rate_limiter.reset()

    user = UserModel(
        email="inactive@test.org",
        password_hash=hash_password("ValidPassword"),
        role="viewer",
        is_active=False,
    )
    auth_db.add(user)
    auth_db.commit()

    res = client.post(
        "/auth/login", json={"email": "inactive@test.org", "password": "ValidPassword"}
    )
    assert res.status_code == 403
    assert "Account is deactivated" in res.json()["detail"]


# ==============================================================================
# 5. Role Matrix Test (Every Endpoint x Every Role)
# ==============================================================================


@pytest.mark.parametrize(
    ("role", "reviewer_status", "researcher_status", "viewer_status"),
    [
        (None, 401, 401, 401),  # Unauthenticated
        (UserRole.VIEWER, 403, 403, 200),  # Viewer: read-only
        (UserRole.RESEARCHER, 403, 200, 200),  # Researcher: research + view
        (UserRole.REVIEWER, 200, 200, 200),  # Reviewer: review + research + view
        (UserRole.ADMIN, 200, 200, 200),  # Admin: full access
    ],
)
def test_role_matrix(
    client: TestClient,
    auth_db: Session,
    role: UserRole | None,
    reviewer_status: int,
    researcher_status: int,
    viewer_status: int,
) -> None:
    """Test full role matrix across permission tiers."""
    headers = {}
    if role is not None:
        user = UserModel(
            email=f"{role.value}@matrix.test",
            password_hash="pwd",
            role=role.value,
            is_active=True,
        )
        auth_db.add(user)
        auth_db.commit()
        token = create_access_token(user_id=user.id, role=user.role)
        headers = {"Authorization": f"Bearer {token}"}

    # Test reviewer-only endpoint
    r1 = client.get("/test/reviewer-only", headers=headers)
    assert (
        r1.status_code == reviewer_status
    ), f"Role {role} on reviewer endpoint got {r1.status_code}"

    # Test researcher-only endpoint
    r2 = client.get("/test/researcher-only", headers=headers)
    assert (
        r2.status_code == researcher_status
    ), f"Role {role} on researcher endpoint got {r2.status_code}"

    # Test viewer-only endpoint
    r3 = client.get("/test/viewer-only", headers=headers)
    assert r3.status_code == viewer_status, f"Role {role} on viewer endpoint got {r3.status_code}"


def test_access_log_created_on_endpoint_access(client: TestClient, auth_db: Session) -> None:
    """Accessing protected endpoints logs audit record in access_log (P7)."""
    user = UserModel(email="audited@doc.org", password_hash="pwd", role="reviewer", is_active=True)
    auth_db.add(user)
    auth_db.commit()

    token = create_access_token(user_id=user.id, role=user.role)
    res = client.get("/test/reviewer-only", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200

    # Verify access_log has entry
    entry = auth_db.execute(
        select(AccessLogModel).where(AccessLogModel.user_id == user.id)
    ).scalar_one_or_none()
    assert entry is not None
    assert entry.action == "review_access"
    assert entry.ts is not None


def test_create_user_service(monkeypatch, auth_db: Session) -> None:
    from surgisight.api import create_user as cu_mod

    monkeypatch.setattr(cu_mod, "SyncSessionLocal", lambda: auth_db)

    u = cu_mod.create_user(email="cli_admin@doc.org", password="pwd", role="admin")
    assert u.id is not None
    assert u.email == "cli_admin@doc.org"
    assert u.role == "admin"

    # Duplicate rejected
    with pytest.raises(ValueError, match="already exists"):
        cu_mod.create_user(email="cli_admin@doc.org", password="pwd", role="viewer")

    # Invalid role rejected
    with pytest.raises(ValueError, match="Invalid role"):
        cu_mod.create_user(email="other@doc.org", password="pwd", role="superman")


def test_refresh_requires_httponly_cookie(client: TestClient) -> None:
    """Refresh endpoint refuses a refresh token supplied in a JSON body or omitted."""
    response = client.post("/auth/refresh", json={"refresh_token": "not-a-cookie"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing refresh cookie."


def test_logout_clears_refresh_cookie(client: TestClient) -> None:
    """Logout expires the HttpOnly refresh cookie at its scoped path."""
    response = client.post("/auth/logout")
    assert response.status_code == 200
    assert response.json()["status"] == "signed_out"
    assert "refresh_token" in response.headers.get("set-cookie", "")
