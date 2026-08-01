"""Fixtures shared by the server integration tests.

These tests hit the REAL database configured in graphify/.env (the same Neon
DB used throughout manual verification this session) rather than an
in-memory one. Two reasons:

1. The models use Postgres-specific column types (dialects.postgresql.UUID,
   native Enum-as-VARCHAR), which don't translate to SQLite — an in-memory
   DB would need either a schema rewrite just for tests or a separate local
   Postgres, neither of which exists yet.
2. It is the only way to test the actual security properties that matter
   here (cookie isolation, real password hashing round trips) rather than a
   mocked stand-in for them.

Every row created by these fixtures is prefixed with ZZ_PYTEST_PREFIX and
deleted in a `finally` block, so a failing test still cleans up. A
session-scoped sweep also runs at the start of the test session to remove
any leftovers from a previous run that crashed before its own cleanup ran.

What these tests deliberately do NOT do: call a real LLM provider, or
trigger a real Railway deploy. The real DB already has a real OpenAI key and
real Railway credentials configured (this is a working dev environment, not
a blank slate) — a naive integration test would spend real money or launch
a real container on every test run. Anything that would reach an external
paid API is monkeypatched instead; see test_launch_routes.py and
test_admin_routes.py for where and why.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, or_

ZZ_PYTEST_PREFIX = "zz-pytest-"


@pytest.fixture(scope="session", autouse=True)
def _sweep_stale_pytest_rows():
    """Best-effort cleanup of rows left behind by a previous crashed run.
    Runs once per test session, before and after."""
    import asyncio

    async def _sweep():
        from graphify.server.db import get_session_factory
        from graphify.server.models import Admin, Project, User

        session_factory = get_session_factory()
        async with session_factory() as db:
            await db.execute(delete(Project).where(Project.repo_name.like(f"{ZZ_PYTEST_PREFIX}%")))
            await db.execute(delete(User).where(User.github_login.like(f"{ZZ_PYTEST_PREFIX}%")))
            await db.execute(delete(Admin).where(Admin.email.like(f"{ZZ_PYTEST_PREFIX}%")))
            await db.commit()

    asyncio.run(_sweep())
    yield
    asyncio.run(_sweep())


@pytest_asyncio.fixture()
async def app_client():
    """An httpx client talking directly to the real FastAPI app in-process —
    no real network socket, but the full real routing/dependency/middleware
    stack, same as a browser would exercise."""
    from graphify.server.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture()
async def test_user():
    """A real, throwaway User row plus a real signed session cookie for it —
    the same create_session_cookie_value() used by the actual login flow, so
    tests exercise the real cookie-reading code path rather than bypassing it
    with a dependency override."""
    from graphify.server.db import get_session_factory
    from graphify.server.models import User
    from graphify.server.sessions import create_session_cookie_value

    session_factory = get_session_factory()
    unique = uuid.uuid4().hex[:8]
    async with session_factory() as db:
        user = User(
            github_user_id=int(unique, 16) % 2_000_000_000,
            github_login=f"{ZZ_PYTEST_PREFIX}{unique}",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id

    cookie = create_session_cookie_value(user_id)
    try:
        yield user_id, cookie
    finally:
        async with session_factory() as db:
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()


@pytest_asyncio.fixture()
async def test_admin():
    """A real, throwaway Admin row with a real argon2 hash for a known
    plaintext password, so login tests exercise the real verify path."""
    from graphify.server.admin_sessions import hash_password
    from graphify.server.db import get_session_factory
    from graphify.server.models import Admin

    session_factory = get_session_factory()
    unique = uuid.uuid4().hex[:8]
    email = f"{ZZ_PYTEST_PREFIX}{unique}@example.com"
    password = "correct-horse-battery-staple-123"

    async with session_factory() as db:
        admin = Admin(email=email, password_hash=hash_password(password))
        db.add(admin)
        await db.commit()
        await db.refresh(admin)
        admin_id = admin.id

    try:
        yield {"id": admin_id, "email": email, "password": password}
    finally:
        async with session_factory() as db:
            await db.execute(delete(Admin).where(Admin.id == admin_id))
            await db.commit()
