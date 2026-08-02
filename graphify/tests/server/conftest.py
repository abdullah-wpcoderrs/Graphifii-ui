"""Fixtures shared by the server integration tests.

Database-backed tests require an explicit `GRAPHIFY_TEST_DATABASE_URL` and
refuse to fall back to the application's `DATABASE_URL`. They use PostgreSQL
rather than an in-memory database for two reasons:

1. The models use Postgres-specific column types (dialects.postgresql.UUID,
   native Enum-as-VARCHAR), which don't translate to SQLite — an in-memory
   DB would need either a schema rewrite just for tests or a separate local
   Postgres, neither of which exists yet.
2. It is the only way to test the actual locking and constraint properties
   that matter rather than a mocked stand-in.

Every row created by these fixtures is prefixed with ZZ_PYTEST_PREFIX and
deleted in a `finally` block, so a failing test still cleans up. A
session-scoped sweep also runs at the start of the test session to remove
any leftovers from a previous run that crashed before its own cleanup ran.

The database must be isolated and disposable. Tests never call a real LLM
provider or trigger Railway; all paid/external boundaries are monkeypatched.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, or_

ZZ_PYTEST_PREFIX = "zz-pytest-"


@pytest.fixture(scope="session")
def _sweep_stale_pytest_rows():
    """Best-effort cleanup of rows left behind by a previous crashed run.
    Runs once per test session, before and after."""
    import asyncio

    test_database_url = os.environ.get("GRAPHIFY_TEST_DATABASE_URL")
    if not test_database_url:
        pytest.skip(
            "database integration tests require GRAPHIFY_TEST_DATABASE_URL; "
            "the application DATABASE_URL is never used for tests"
        )

    os.environ["DATABASE_URL"] = test_database_url
    from graphify.server.config import get_settings

    get_settings.cache_clear()

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
async def app_client(_sweep_stale_pytest_rows):
    """An httpx client talking directly to the real FastAPI app in-process —
    no real network socket, but the full real routing/dependency/middleware
    stack, same as a browser would exercise.

    Sends a default Origin header matching the configured frontend_url, the
    same way a real browser's fetch() would on every request. Without this,
    every state-changing test (POST/PUT/PATCH/DELETE with a real session
    cookie) would be rejected by CSRFOriginMiddleware — the middleware exists
    precisely to reject an unsafe request whose Origin doesn't match, and an
    httpx client sends no Origin at all unless told to. A test that wants to
    exercise the *rejection* path should override this header per-request.
    """
    from graphify.server.app import app
    from graphify.server.config import get_settings

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"origin": get_settings().frontend_url},
    ) as client:
        yield client


@pytest_asyncio.fixture()
async def test_user(_sweep_stale_pytest_rows):
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
async def test_admin(_sweep_stale_pytest_rows):
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
