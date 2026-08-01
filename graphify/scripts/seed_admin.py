"""Seed or update the platform administrator in public.admin.

Reads credentials from the environment so no plaintext password is ever
written to a migration, a source file, or shell history in this repo:

    ADMIN_EMAIL=you@example.com ADMIN_PASSWORD='...' uv run python scripts/seed_admin.py

Or set both in graphify/.env (already gitignored) and run:

    uv run python scripts/seed_admin.py

Re-running with the same email updates that admin's password rather than
creating a duplicate, so this doubles as a password-reset path. Only the
argon2 hash is persisted.

Deliberately a standalone script rather than an auto-seed on app startup:
seeding is an operator action that should happen once, on purpose, not
silently on every deploy.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import select

from graphify.server.admin_sessions import hash_password
from graphify.server.db import get_session_factory
from graphify.server.models import Admin

MIN_PASSWORD_LENGTH = 12


def _from_env_file(key: str) -> str | None:
    """Read a key from graphify/.env.

    The server reads .env through pydantic-settings, but this script runs
    standalone and os.environ alone would miss values that live only in the
    file — which is exactly where the docs tell operators to put them.
    A real environment variable still wins, so CI can override.
    """
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return None


def _read(key: str) -> str:
    return (os.environ.get(key) or _from_env_file(key) or "").strip()


async def seed() -> int:
    email = _read("ADMIN_EMAIL").lower()
    password = _read("ADMIN_PASSWORD")

    if not email or not password:
        print(
            "ERROR: ADMIN_EMAIL and ADMIN_PASSWORD must both be set.\n"
            "  ADMIN_EMAIL=you@example.com ADMIN_PASSWORD='...' "
            "uv run python scripts/seed_admin.py",
            file=sys.stderr,
        )
        return 1

    if "@" not in email:
        print(f"ERROR: ADMIN_EMAIL {email!r} does not look like an email address.", file=sys.stderr)
        return 1

    if len(password) < MIN_PASSWORD_LENGTH:
        print(
            f"ERROR: ADMIN_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters. "
            "This account manages provider API keys and user data.",
            file=sys.stderr,
        )
        return 1

    session_factory = get_session_factory()
    async with session_factory() as db:
        result = await db.execute(select(Admin).where(Admin.email == email))
        admin = result.scalar_one_or_none()

        if admin is None:
            db.add(Admin(email=email, password_hash=hash_password(password)))
            action = "created"
        else:
            admin.password_hash = hash_password(password)
            admin.is_active = True
            action = "updated (password reset)"

        await db.commit()

    print(f"Admin {action}: {email}")
    if not _read("ADMIN_SESSION_SECRET"):
        print(
            "WARNING: ADMIN_SESSION_SECRET is not set — /api/admin/login will "
            "return 503 until it is. Generate one with:\n"
            "  python3 -c 'import secrets; print(secrets.token_urlsafe(48))'",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(seed()))
