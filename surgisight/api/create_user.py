"""CLI utility for administrative user creation.

Usage:
    python -m surgisight.api.create_user --email admin@surgisight.org --password secret --role admin
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from surgisight.api.auth import hash_password
from surgisight.contract.types import UserRole
from surgisight.db import SyncSessionLocal, UserModel


def create_user(email: str, password: str, role: str, is_active: bool = True) -> UserModel:
    """Create a user with hashed password in database."""
    # Validate role
    valid_roles = [r.value for r in UserRole]
    if role not in valid_roles:
        raise ValueError(f"Invalid role '{role}'. Allowed roles: {valid_roles}")

    normalized_email = email.strip().lower()

    with SyncSessionLocal() as session:
        existing = session.execute(
            select(UserModel).where(UserModel.email == normalized_email)
        ).scalar_one_or_none()

        if existing:
            raise ValueError(f"User with email '{normalized_email}' already exists.")

        user = UserModel(
            email=normalized_email,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a SurgiSight user account")
    parser.add_argument("--email", required=True, help="User email address")
    parser.add_argument("--password", required=True, help="User password")
    parser.add_argument(
        "--role",
        default="viewer",
        choices=[r.value for r in UserRole],
        help="Access role (admin, reviewer, researcher, viewer)",
    )
    parser.add_argument(
        "--inactive",
        action="store_true",
        help="Create account in deactivated state",
    )

    args = parser.parse_args()

    try:
        user = create_user(
            email=args.email,
            password=args.password,
            role=args.role,
            is_active=not args.inactive,
        )
        print(f"Successfully created user '{user.email}' with ID {user.id} and role '{user.role}'.")
    except Exception as exc:
        print(f"Error creating user: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
