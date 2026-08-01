"""Integration tests for graphify/server/routes/launch.py against the real
DB. See conftest.py for why real DB + no real external calls.

POST /api/projects's success path (the part that would call the real
Railway API) is deliberately NOT tested here — see test_launch_no_llm_key_
returns_503_before_ever_calling_railway and the module docstring in
conftest.py. Everything that happens *after* a real launch (status
callback, artifacts upload, usage report, WebSocket streaming) IS tested
against the real DB, because none of that reaches Railway or a paid API —
it's the receiving end of what a real sandbox would send.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import websockets
from sqlalchemy import delete

from graphify.server.config import get_settings
from graphify.server.db import get_session_factory
from graphify.server.models import Project, ProjectStatus
from tests.server.conftest import ZZ_PYTEST_PREFIX



# --- POST /api/projects: everything before a real Railway call -------------


async def test_launch_requires_authentication(app_client):
    resp = await app_client.post(
        "/api/projects", json={"repo_full_name": "a/b", "repo_url": "https://github.com/a/b.git"}
    )
    assert resp.status_code == 401


async def test_launch_rejects_unknown_provider(app_client, test_user):
    _, cookie = test_user
    resp = await app_client.post(
        "/api/projects",
        json={
            "repo_full_name": "a/b",
            "repo_url": "https://github.com/a/b.git",
            "provider": "bitbucket",  # not a real supported provider
        },
        cookies={"graphify_session": cookie},
    )
    assert resp.status_code == 400


async def test_launch_returns_409_for_an_already_in_flight_project(app_client, test_user):
    """The route must refuse to double-launch a repo that's already
    CLONING/INDEXING — interrupting it would orphan the running Railway job.
    Set up by inserting the in-flight row directly, never by actually
    launching, so this never reaches Railway."""
    user_id, cookie = test_user
    session_factory = get_session_factory()
    repo_name = f"{ZZ_PYTEST_PREFIX}inflight/repo"

    async with session_factory() as db:
        project = Project(
            user_id=user_id,
            repo_name=repo_name,
            repo_url="https://github.com/x/y.git",
            status=ProjectStatus.CLONING,
        )
        db.add(project)
        await db.commit()

    try:
        resp = await app_client.post(
            "/api/projects",
            json={
                "repo_full_name": repo_name,
                "repo_url": "https://github.com/x/y.git",
                "provider": "github",
            },
            cookies={"graphify_session": cookie},
        )
        assert resp.status_code == 409
    finally:
        async with session_factory() as db:
            await db.execute(delete(Project).where(Project.repo_name == repo_name))
            await db.commit()


async def test_launch_returns_503_when_no_llm_credential_is_configured(app_client, test_user, monkeypatch):
    """Must fail BEFORE calling Railway. Monkeypatched rather than deleting
    the real SystemCredential row — this dev DB has a real configured key
    and a test must not mutate that shared state."""
    from graphify.server.routes import launch as launch_module
    from fastapi import HTTPException

    async def _raise_not_configured(db):
        raise HTTPException(status_code=503, detail="No LLM provider is configured")

    monkeypatch.setattr(launch_module, "_active_llm_credential", _raise_not_configured)

    _, cookie = test_user
    resp = await app_client.post(
        "/api/projects",
        json={
            "repo_full_name": f"{ZZ_PYTEST_PREFIX}whatever/repo",
            "repo_url": "https://github.com/x/y.git",
            "provider": "github",
        },
        cookies={"graphify_session": cookie},
    )
    assert resp.status_code == 503


# --- POST /api/internal/projects/{id}/status --------------------------------


@pytest.fixture()
async def throwaway_project(test_user):
    user_id, _ = test_user
    session_factory = get_session_factory()
    async with session_factory() as db:
        project = Project(
            user_id=user_id,
            repo_name=f"{ZZ_PYTEST_PREFIX}callback/repo-{uuid.uuid4().hex[:8]}",
            repo_url="https://github.com/x/y.git",
            status=ProjectStatus.CLONING,
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)
        project_id = project.id
    try:
        yield project_id
    finally:
        async with session_factory() as db:
            await db.execute(delete(Project).where(Project.id == project_id))
            await db.commit()


async def test_status_callback_rejects_wrong_secret(app_client, throwaway_project):
    resp = await app_client.post(
        f"/api/internal/projects/{throwaway_project}/status",
        json={"status": "INDEXING"},
        headers={"X-Sandbox-Secret": "definitely-wrong"},
    )
    assert resp.status_code == 401


async def test_status_callback_rejects_invalid_status_value(app_client, throwaway_project):
    secret = get_settings().sandbox_callback_secret
    resp = await app_client.post(
        f"/api/internal/projects/{throwaway_project}/status",
        json={"status": "NOT_A_REAL_STATUS"},
        headers={"X-Sandbox-Secret": secret},
    )
    assert resp.status_code == 400


async def test_status_callback_updates_progress_and_ignores_late_callbacks_after_terminal(
    app_client, throwaway_project
):
    secret = get_settings().sandbox_callback_secret

    resp = await app_client.post(
        f"/api/internal/projects/{throwaway_project}/status",
        json={"status": "READY", "progress_percent": 100, "graph_json_url": "/tmp/g.json"},
        headers={"X-Sandbox-Secret": secret},
    )
    assert resp.status_code == 200

    session_factory = get_session_factory()
    async with session_factory() as db:
        project = await db.get(Project, throwaway_project)
        assert project.status is ProjectStatus.READY
        assert project.progress_percent == 100

    # A callback arriving after READY must be ignored, not resurrect the project.
    resp = await app_client.post(
        f"/api/internal/projects/{throwaway_project}/status",
        json={"status": "INDEXING", "progress_percent": 10},
        headers={"X-Sandbox-Secret": secret},
    )
    body = resp.json()
    assert "ignored" in body

    async with session_factory() as db:
        project = await db.get(Project, throwaway_project)
        assert project.status is ProjectStatus.READY  # unchanged


# --- POST /api/internal/projects/{id}/usage ---------------------------------


async def test_usage_report_rejects_wrong_secret(app_client, throwaway_project):
    resp = await app_client.post(
        f"/api/internal/projects/{throwaway_project}/usage",
        json={"provider": "openai", "model": "x", "prompt_tokens": 1, "completion_tokens": 1},
        headers={"X-Sandbox-Secret": "wrong"},
    )
    assert resp.status_code == 401


async def test_usage_report_records_a_real_usage_event_attributed_to_the_owner(
    app_client, throwaway_project, test_user
):
    from sqlalchemy import select

    from graphify.server.models import UsageEvent

    user_id, _ = test_user
    secret = get_settings().sandbox_callback_secret

    resp = await app_client.post(
        f"/api/internal/projects/{throwaway_project}/usage",
        json={
            "provider": "openai",
            "model": "openai (sandbox default)",
            "operation": "extraction",
            "prompt_tokens": 4200,
            "completion_tokens": 850,
        },
        headers={"X-Sandbox-Secret": secret},
    )
    assert resp.status_code == 200

    session_factory = get_session_factory()
    async with session_factory() as db:
        event = (
            await db.execute(select(UsageEvent).where(UsageEvent.project_id == throwaway_project))
        ).scalar_one_or_none()
        try:
            assert event is not None
            assert event.user_id == user_id
            assert event.prompt_tokens == 4200
            assert event.completion_tokens == 850
            assert event.cost_estimate > 0
        finally:
            if event is not None:
                await db.delete(event)
                await db.commit()


# --- WS /ws/projects/{id} ----------------------------------------------------


def test_websocket_rejects_missing_and_forged_cookies():
    """FastAPI's TestClient drives a real WebSocket handshake in-process
    (no real network socket, but the real ASGI protocol) — this is not a
    weaker substitute for a live connection, it exercises the exact code
    path a browser would hit. Plain `def`, not `async def`: TestClient
    manages its own event loop internally and must not be nested inside
    pytest-asyncio's."""
    from fastapi.testclient import TestClient
    from websockets.exceptions import ConnectionClosed

    from graphify.server.app import app

    client = TestClient(app)
    fake_project_id = uuid.uuid4()

    with pytest.raises(Exception) as exc_info:
        with client.websocket_connect(f"/ws/projects/{fake_project_id}") as ws:
            ws.receive_json()
    assert getattr(exc_info.value, "code", None) == 4401

    with pytest.raises(Exception) as exc_info:
        with client.websocket_connect(
            f"/ws/projects/{fake_project_id}",
            cookies={"graphify_session": "forged.garbage.value"},
        ) as ws:
            ws.receive_json()
    assert getattr(exc_info.value, "code", None) == 4401


async def test_websocket_rejects_a_project_belonging_to_someone_else(app_client, test_user, throwaway_project):
    """A second, different authenticated user must be rejected exactly like
    an unauthenticated one — the route deliberately doesn't distinguish
    "not found" from "not yours", so it can't be used to enumerate project
    ids that belong to other users."""
    from graphify.server.db import get_session_factory
    from graphify.server.models import User
    from graphify.server.sessions import create_session_cookie_value
    from fastapi.testclient import TestClient
    from graphify.server.app import app

    session_factory = get_session_factory()
    unique = uuid.uuid4().hex[:8]
    async with session_factory() as db:
        other_user = User(
            github_user_id=int(unique, 16) % 2_000_000_000,
            github_login=f"{ZZ_PYTEST_PREFIX}other-{unique}",
        )
        db.add(other_user)
        await db.commit()
        await db.refresh(other_user)
        other_user_id = other_user.id

    try:
        other_cookie = create_session_cookie_value(other_user_id)
        client = TestClient(app)
        with pytest.raises(Exception) as exc_info:
            with client.websocket_connect(
                f"/ws/projects/{throwaway_project}",
                cookies={"graphify_session": other_cookie},
            ) as ws:
                ws.receive_json()
        assert getattr(exc_info.value, "code", None) == 4404
    finally:
        from sqlalchemy import delete

        async with session_factory() as db:
            await db.execute(delete(User).where(User.id == other_user_id))
            await db.commit()
