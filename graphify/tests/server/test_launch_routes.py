"""Launch tests against an explicit isolated PostgreSQL test database.

Railway and LLM calls are deterministic fakes; database locks and unique
constraints remain real.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
import websockets
from sqlalchemy import delete, select

from graphify.server.db import get_session_factory
from graphify.server.models import ExtractionRun, ExtractionRunStatus, Project, ProjectStatus
from graphify.server.run_service import hash_callback_secret
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
        await db.flush()
        run = ExtractionRun(
            project_id=project.id,
            status=ExtractionRunStatus.INDEXING,
            active_slot=1,
            repo_url=project.repo_url,
            repo_full_name=project.repo_name,
            provider="github",
            default_branch="main",
            llm_provider="openai",
            callback_secret_hash=hash_callback_secret("test-secret"),
        )
        db.add(run)
        await db.flush()
        project.current_run_id = run.id
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


async def test_ready_project_rerun_creates_a_fresh_immutable_run(
    app_client, test_user, monkeypatch
):
    """The dashboard/workspace rerun action reuses the stable Project row but
    must create a new ExtractionRun and clear every projection of the previous
    READY attempt. The old run remains immutable history."""
    from types import SimpleNamespace

    from graphify.server.routes import launch as launch_module

    user_id, cookie = test_user
    session_factory = get_session_factory()
    repo_name = f"{ZZ_PYTEST_PREFIX}rerun/repo-{uuid.uuid4().hex[:8]}"

    async with session_factory() as db:
        project = Project(
            user_id=user_id,
            repo_name=repo_name,
            repo_url="https://github.com/x/original.git",
            default_branch="main",
            provider="github",
            status=ProjectStatus.READY,
            progress_percent=100,
            status_message="Extraction complete",
            graph_json_url="/data/workspaces/old-run/graph.json",
        )
        db.add(project)
        await db.flush()
        previous_run = ExtractionRun(
            project_id=project.id,
            status=ExtractionRunStatus.READY,
            repo_url=project.repo_url,
            repo_full_name=project.repo_name,
            provider=project.provider,
            default_branch=project.default_branch,
            llm_provider="openai",
            progress_percent=100,
            status_message="Extraction complete",
        )
        db.add(previous_run)
        await db.flush()
        project.current_run_id = previous_run.id
        await db.commit()
        project_id = project.id
        previous_run_id = previous_run.id

    async def fake_credential(_db):
        return SimpleNamespace(provider="openai", model="gpt-4.1-mini")

    monkeypatch.setattr(launch_module, "_active_llm_credential", fake_credential)

    try:
        response = await app_client.post(
            "/api/projects",
            json={
                "repo_full_name": repo_name,
                "repo_url": "https://github.com/x/original.git",
                "provider": "github",
                "default_branch": "main",
            },
            cookies={"graphify_session": cookie},
        )

        assert response.status_code == 200
        assert response.json() == {
            "project_id": str(project_id),
            "run_id": response.json()["run_id"],
            "status": "CLONING",
            "progress_percent": 0,
            "message": "Queued for provisioning",
            "error": None,
            "graph_json_url": None,
            "terminal": False,
            "updated_at": response.json()["updated_at"],
        }

        async with session_factory() as db:
            persisted_project = await db.get(Project, project_id)
            runs = (
                await db.execute(
                    select(ExtractionRun)
                    .where(ExtractionRun.project_id == project_id)
                    .order_by(ExtractionRun.created_at)
                )
            ).scalars().all()

        assert persisted_project is not None
        assert persisted_project.current_run_id != previous_run_id
        assert persisted_project.graph_json_url is None
        assert persisted_project.progress_percent == 0
        assert len(runs) == 2
        assert runs[0].id == previous_run_id
        assert runs[0].status is ExtractionRunStatus.READY
        assert runs[1].id == persisted_project.current_run_id
        assert runs[1].status is ExtractionRunStatus.QUEUED
        assert runs[1].llm_provider == "openai"
        assert runs[1].llm_model == "gpt-4.1-mini"
    finally:
        async with session_factory() as db:
            await db.execute(delete(Project).where(Project.id == project_id))
            await db.commit()


async def test_launch_returns_503_when_no_llm_credential_is_configured(
    app_client, test_user, monkeypatch
):
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
async def throwaway_run(test_user):
    user_id, _ = test_user
    session_factory = get_session_factory()
    callback_secret = f"test-secret-{uuid.uuid4().hex}"
    async with session_factory() as db:
        project = Project(
            user_id=user_id,
            repo_name=f"{ZZ_PYTEST_PREFIX}callback/repo-{uuid.uuid4().hex[:8]}",
            repo_url="https://github.com/x/y.git",
            status=ProjectStatus.CLONING,
        )
        db.add(project)
        await db.flush()
        run = ExtractionRun(
            project_id=project.id,
            status=ExtractionRunStatus.INDEXING,
            active_slot=1,
            repo_url=project.repo_url,
            repo_full_name=project.repo_name,
            provider="github",
            default_branch="main",
            llm_provider="openai",
            callback_secret_hash=hash_callback_secret(callback_secret),
            progress_percent=25,
        )
        db.add(run)
        await db.flush()
        project.current_run_id = run.id
        await db.commit()
        await db.refresh(project)
        project_id = project.id
        run_id = run.id
    try:
        yield {"project_id": project_id, "run_id": run_id, "secret": callback_secret}
    finally:
        async with session_factory() as db:
            await db.execute(delete(Project).where(Project.id == project_id))
            await db.commit()


async def test_status_callback_rejects_wrong_secret(app_client, throwaway_run):
    resp = await app_client.post(
        f"/api/internal/projects/{throwaway_run['project_id']}/runs/{throwaway_run['run_id']}/status",
        json={"status": "INDEXING"},
        headers={
            "X-Sandbox-Secret": "definitely-wrong",
            "X-Sandbox-Event-Id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 401


async def test_status_callback_rejects_invalid_status_value(app_client, throwaway_run):
    resp = await app_client.post(
        f"/api/internal/projects/{throwaway_run['project_id']}/runs/{throwaway_run['run_id']}/status",
        json={"status": "NOT_A_REAL_STATUS"},
        headers={
            "X-Sandbox-Secret": throwaway_run["secret"],
            "X-Sandbox-Event-Id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 422


async def test_status_callback_updates_progress_and_ignores_late_callbacks_after_terminal(
    app_client, throwaway_run, monkeypatch
):
    from graphify.server.routes import launch as launch_module

    async def fake_clear():
        return None

    monkeypatch.setattr(launch_module, "clear_sandbox_variables_on_railway", fake_clear)
    event_id = uuid.uuid4()

    resp = await app_client.post(
        f"/api/internal/projects/{throwaway_run['project_id']}/runs/{throwaway_run['run_id']}/status",
        json={"status": "READY", "progress_percent": 100},
        headers={
            "X-Sandbox-Secret": throwaway_run["secret"],
            "X-Sandbox-Event-Id": str(event_id),
        },
    )
    assert resp.status_code == 200

    session_factory = get_session_factory()
    async with session_factory() as db:
        project = await db.get(Project, throwaway_run["project_id"])
        assert project.status is ProjectStatus.READY
        assert project.progress_percent == 100

    # A retry with the same event id is idempotent.
    resp = await app_client.post(
        f"/api/internal/projects/{throwaway_run['project_id']}/runs/{throwaway_run['run_id']}/status",
        json={"status": "READY", "progress_percent": 100},
        headers={
            "X-Sandbox-Secret": throwaway_run["secret"],
            "X-Sandbox-Event-Id": str(event_id),
        },
    )
    body = resp.json()
    assert body["duplicate"] is True

    # A new event cannot regress a terminal run.
    resp = await app_client.post(
        f"/api/internal/projects/{throwaway_run['project_id']}/runs/{throwaway_run['run_id']}/status",
        json={"status": "INDEXING", "progress_percent": 10},
        headers={
            "X-Sandbox-Secret": throwaway_run["secret"],
            "X-Sandbox-Event-Id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 409

    async with session_factory() as db:
        project = await db.get(Project, throwaway_run["project_id"])
        assert project.status is ProjectStatus.READY  # unchanged


# --- POST /api/internal/projects/{id}/usage ---------------------------------


async def test_usage_report_rejects_wrong_secret(app_client, throwaway_run):
    resp = await app_client.post(
        f"/api/internal/projects/{throwaway_run['project_id']}/runs/{throwaway_run['run_id']}/usage",
        json={"provider": "openai", "model": "x", "prompt_tokens": 1, "completion_tokens": 1},
        headers={"X-Sandbox-Secret": "wrong", "X-Sandbox-Event-Id": str(uuid.uuid4())},
    )
    assert resp.status_code == 401


async def test_usage_report_records_a_real_usage_event_attributed_to_the_owner(
    app_client, throwaway_run, test_user
):
    from sqlalchemy import select

    from graphify.server.models import UsageEvent

    user_id, _ = test_user
    event_id = uuid.uuid4()

    resp = await app_client.post(
        f"/api/internal/projects/{throwaway_run['project_id']}/runs/{throwaway_run['run_id']}/usage",
        json={
            "provider": "openai",
            "model": "openai (sandbox default)",
            "operation": "extraction",
            "prompt_tokens": 4200,
            "completion_tokens": 850,
        },
        headers={
            "X-Sandbox-Secret": throwaway_run["secret"],
            "X-Sandbox-Event-Id": str(event_id),
        },
    )
    assert resp.status_code == 200

    session_factory = get_session_factory()
    async with session_factory() as db:
        event = (
            await db.execute(select(UsageEvent).where(UsageEvent.run_id == throwaway_run["run_id"]))
        ).scalar_one_or_none()
        try:
            assert event is not None
            assert event.user_id == user_id
            assert event.prompt_tokens == 4200
            assert event.completion_tokens == 850
            assert event.cost_estimate > 0
            assert event.run_id == throwaway_run["run_id"]
        finally:
            if event is not None:
                await db.delete(event)
                await db.commit()


async def test_usage_callback_retry_is_recorded_exactly_once(app_client, throwaway_run):
    from sqlalchemy import func, select

    from graphify.server.models import UsageEvent

    event_id = uuid.uuid4()
    url = (
        f"/api/internal/projects/{throwaway_run['project_id']}/runs/{throwaway_run['run_id']}/usage"
    )
    kwargs = {
        "json": {
            "provider": "openai",
            "model": "openai (sandbox default)",
            "operation": "extraction",
            "prompt_tokens": 100,
            "completion_tokens": 25,
        },
        "headers": {
            "X-Sandbox-Secret": throwaway_run["secret"],
            "X-Sandbox-Event-Id": str(event_id),
        },
    }

    first = await app_client.post(url, **kwargs)
    second = await app_client.post(url, **kwargs)
    assert first.status_code == 200
    assert second.json()["duplicate"] is True

    session_factory = get_session_factory()
    async with session_factory() as db:
        count = (
            await db.execute(
                select(func.count())
                .select_from(UsageEvent)
                .where(UsageEvent.run_id == throwaway_run["run_id"])
            )
        ).scalar_one()
        assert count == 1


async def test_cancel_revokes_callback_and_stops_exact_deployment(
    app_client, throwaway_run, test_user, monkeypatch
):
    from graphify.server.routes import launch as launch_module

    stopped = []

    async def fake_cancel(deployment_id):
        stopped.append(deployment_id)

    async def fake_clear():
        return None

    monkeypatch.setattr(launch_module, "cancel_deployment_on_railway", fake_cancel)
    monkeypatch.setattr(launch_module, "clear_sandbox_variables_on_railway", fake_clear)
    session_factory = get_session_factory()
    async with session_factory() as db:
        run = await db.get(ExtractionRun, throwaway_run["run_id"])
        run.deployment_id = "deployment-to-stop"
        await db.commit()

    _, cookie = test_user
    response = await app_client.post(
        f"/api/projects/{throwaway_run['project_id']}/cancel",
        cookies={"graphify_session": cookie},
    )
    assert response.status_code == 200
    assert stopped == ["deployment-to-stop"]

    async with session_factory() as db:
        run = await db.get(ExtractionRun, throwaway_run["run_id"])
        assert run.status is ExtractionRunStatus.CANCELED
        assert run.callback_secret_hash is None
        assert run.active_slot is None


async def test_old_run_callback_is_rejected_after_relaunch(app_client, throwaway_run):
    session_factory = get_session_factory()
    async with session_factory() as db:
        old = await db.get(ExtractionRun, throwaway_run["run_id"])
        old.active_slot = None
        replacement = ExtractionRun(
            project_id=throwaway_run["project_id"],
            status=ExtractionRunStatus.QUEUED,
            repo_url=old.repo_url,
            repo_full_name=old.repo_full_name,
            provider=old.provider,
            default_branch=old.default_branch,
            llm_provider=old.llm_provider,
        )
        db.add(replacement)
        await db.flush()
        project = await db.get(Project, throwaway_run["project_id"])
        project.current_run_id = replacement.id
        await db.commit()

    response = await app_client.post(
        f"/api/internal/projects/{throwaway_run['project_id']}"
        f"/runs/{throwaway_run['run_id']}/status",
        json={"status": "INDEXING", "progress_percent": 50},
        headers={
            "X-Sandbox-Secret": throwaway_run["secret"],
            "X-Sandbox-Event-Id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 409


async def test_two_dispatchers_cannot_claim_the_shared_service_concurrently(test_user, monkeypatch):
    from graphify.server import run_worker

    user_id, _ = test_user
    session_factory = get_session_factory()
    project_ids = []
    async with session_factory() as db:
        for suffix in ("a", "b"):
            project = Project(
                user_id=user_id,
                repo_name=f"{ZZ_PYTEST_PREFIX}queue/{suffix}-{uuid.uuid4().hex[:8]}",
                repo_url=f"https://github.com/test/{suffix}.git",
                status=ProjectStatus.CLONING,
            )
            db.add(project)
            await db.flush()
            run = ExtractionRun(
                project_id=project.id,
                status=ExtractionRunStatus.QUEUED,
                repo_url=project.repo_url,
                repo_full_name=project.repo_name,
                provider="github",
                default_branch="main",
                llm_provider="openai",
            )
            db.add(run)
            await db.flush()
            project.current_run_id = run.id
            project_ids.append(project.id)
        await db.commit()

    launched = []

    async def fake_inputs(run_id):
        return {
            "project_id": "project",
            "run_id": str(run_id),
            "repo_url": "https://github.com/test/repo.git",
            "default_branch": "main",
            "active_llm_provider": "openai",
            "active_llm_key": "test-key",
            "repo_token": None,
        }

    async def fake_launch(**kwargs):
        launched.append(kwargs["run_id"])
        return {"id": f"deployment-{kwargs['run_id']}"}

    monkeypatch.setattr(run_worker, "_load_launch_inputs", fake_inputs)
    monkeypatch.setattr(run_worker, "launch_project_on_railway", fake_launch)

    results = await asyncio.gather(
        run_worker.dispatch_next_run("worker-a"),
        run_worker.dispatch_next_run("worker-b"),
    )
    assert sum(bool(result) for result in results) == 1
    assert len(launched) == 1

    async with session_factory() as db:
        for project_id in project_ids:
            await db.execute(delete(Project).where(Project.id == project_id))
        await db.commit()


async def test_cancel_during_deploy_trigger_stops_and_releases_the_shared_slot(
    test_user, monkeypatch
):
    from graphify.server import run_worker

    user_id, _ = test_user
    session_factory = get_session_factory()
    async with session_factory() as db:
        project = Project(
            user_id=user_id,
            repo_name=f"{ZZ_PYTEST_PREFIX}cancel-race/{uuid.uuid4().hex[:8]}",
            repo_url="https://github.com/test/cancel-race.git",
            status=ProjectStatus.CLONING,
        )
        db.add(project)
        await db.flush()
        run = ExtractionRun(
            project_id=project.id,
            status=ExtractionRunStatus.QUEUED,
            repo_url=project.repo_url,
            repo_full_name=project.repo_name,
            provider="github",
            default_branch="main",
            llm_provider="openai",
        )
        db.add(run)
        await db.flush()
        project.current_run_id = run.id
        run_id = run.id
        project_id = project.id
        await db.commit()

    async def fake_inputs(claimed_run_id):
        return {
            "project_id": str(project_id),
            "run_id": str(claimed_run_id),
            "repo_url": "https://github.com/test/cancel-race.git",
            "default_branch": "main",
            "active_llm_provider": "openai",
            "active_llm_key": "test-key",
            "repo_token": None,
        }

    async def fake_launch(**_kwargs):
        async with session_factory() as db:
            persisted = await db.get(ExtractionRun, run_id)
            persisted.status = ExtractionRunStatus.CANCELED
            persisted.callback_secret_hash = None
            await db.commit()
        return {"id": "deployment-cancel-race"}

    stopped = []
    cleared = []

    async def fake_cancel(deployment_id):
        stopped.append(deployment_id)

    async def fake_clear():
        cleared.append(True)

    monkeypatch.setattr(run_worker, "_load_launch_inputs", fake_inputs)
    monkeypatch.setattr(run_worker, "launch_project_on_railway", fake_launch)
    monkeypatch.setattr(run_worker, "cancel_deployment_on_railway", fake_cancel)
    monkeypatch.setattr(run_worker, "clear_sandbox_variables_on_railway", fake_clear)

    assert await run_worker.dispatch_next_run("worker-cancel-race") is True
    assert stopped == ["deployment-cancel-race"]
    assert cleared == [True]

    async with session_factory() as db:
        persisted = await db.get(ExtractionRun, run_id)
        assert persisted.status is ExtractionRunStatus.CANCELED
        assert persisted.active_slot is None
        await db.execute(delete(Project).where(Project.id == project_id))
        await db.commit()


# --- WS /ws/projects/{id} ----------------------------------------------------


async def test_websocket_disconnect_during_initial_snapshot_is_normal(monkeypatch):
    """A browser may replace its first socket during hydration after the
    handshake but before the initial snapshot is sent. That must end quietly
    instead of escaping as an ASGI application error."""
    from types import SimpleNamespace
    from typing import Any, cast

    from fastapi import WebSocketDisconnect

    from graphify.server.routes import launch as launch_module

    project = SimpleNamespace(
        id=uuid.uuid4(),
        current_run_id=uuid.uuid4(),
        status=ProjectStatus.CLONING,
        progress_percent=0,
        status_message="Queued for provisioning",
        error_message=None,
        graph_json_url=None,
        updated_at=None,
    )

    class DisconnectingWebSocket:
        accepted = False
        sends = 0

        async def accept(self):
            self.accepted = True

        async def send_json(self, _payload):
            self.sends += 1
            raise WebSocketDisconnect(code=1006)

    async def fake_authenticate(_websocket, _project_id):
        return project

    monkeypatch.setattr(launch_module, "_authenticate_ws", fake_authenticate)
    websocket = DisconnectingWebSocket()

    await launch_module.project_progress_ws(cast(Any, websocket), project.id)

    assert websocket.accepted is True
    assert websocket.sends == 1


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


async def test_websocket_rejects_a_project_belonging_to_someone_else(
    app_client, test_user, throwaway_run
):
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
                f"/ws/projects/{throwaway_run['project_id']}",
                cookies={"graphify_session": other_cookie},
            ) as ws:
                ws.receive_json()
        assert getattr(exc_info.value, "code", None) == 4404
    finally:
        from sqlalchemy import delete

        async with session_factory() as db:
            await db.execute(delete(User).where(User.id == other_user_id))
            await db.commit()
