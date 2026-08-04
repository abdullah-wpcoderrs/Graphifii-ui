"""Integration tests for POST /api/projects/{id}/pull-request.

Exercises the real FastAPI app + real database rows (Project,
ProjectAgentChange) through app_client, following the fixture style used in
test_launch_routes.py. The actual git provider is never called: build_repo_client
is monkeypatched on the agent routes module to return a fake client whose
methods are AsyncMocks, so this tests the endpoint's own logic (ownership,
validation, status transitions, error mapping) rather than repo_api.py itself
(covered separately in test_repo_api.py).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import delete, select

from graphify.server.crypto import encrypt
from graphify.server.db import get_session_factory
from graphify.server.models import ChangeStatus, Project, ProjectAgentChange
from graphify.server.repo_api import PullRequestResult, RepoConflictError, RepoError
from tests.server.conftest import ZZ_PYTEST_PREFIX


async def _make_project(user_id, *, provider="github", with_token=True):
    session_factory = get_session_factory()
    repo_name = f"{ZZ_PYTEST_PREFIX}pr/repo-{uuid.uuid4().hex[:8]}"
    async with session_factory() as db:
        project = Project(
            user_id=user_id,
            repo_name=repo_name,
            repo_url=f"https://example.test/{repo_name}.git",
            default_branch="main",
            provider=provider,
        )
        db.add(project)
        await db.flush()
        project_id = project.id
        await db.commit()

    if with_token:
        session_factory2 = get_session_factory()
        async with session_factory2() as db:
            from graphify.server.models import User

            user = await db.get(User, user_id)
            ciphertext, iv = encrypt("test-token")
            field = {"github": "github", "gitlab": "gitlab", "gitbucket": "gitbucket"}[provider]
            setattr(user, f"{field}_access_token_ciphertext", ciphertext)
            setattr(user, f"{field}_access_token_iv", iv)
            await db.commit()

    return project_id


async def _make_change(project_id, *, path="a.py", after="x = 1", before=None, status=ChangeStatus.PROPOSED):
    session_factory = get_session_factory()
    async with session_factory() as db:
        change = ProjectAgentChange(
            project_id=project_id,
            path=path,
            before_content=before,
            after_content=after,
            base_sha="orig-sha" if before is not None else None,
            status=status,
        )
        db.add(change)
        await db.commit()
        await db.refresh(change)
        return change.id


async def _cleanup(project_id):
    session_factory = get_session_factory()
    async with session_factory() as db:
        await db.execute(delete(ProjectAgentChange).where(ProjectAgentChange.project_id == project_id))
        await db.execute(delete(Project).where(Project.id == project_id))
        await db.commit()


def _install_fake_client(monkeypatch, client):
    from graphify.server.routes import agent as agent_module

    monkeypatch.setattr(agent_module, "build_repo_client", lambda *a, **k: client)


def _fake_client(*, branch_error=None, commit_error=None, pr_error=None, pr_result=None):
    client = SimpleNamespace()
    if branch_error:
        client.create_branch = AsyncMock(side_effect=branch_error)
    else:
        client.create_branch = AsyncMock(return_value="base-sha")

    if commit_error:
        client.commit_files = AsyncMock(side_effect=commit_error)
    else:
        client.commit_files = AsyncMock(return_value="commit-sha")

    if pr_error:
        client.open_pull_request = AsyncMock(side_effect=pr_error)
    else:
        client.open_pull_request = AsyncMock(
            return_value=pr_result or PullRequestResult(number=1, url="https://x/1", branch="graphify/agent-x")
        )
    return client


async def test_requires_authentication(app_client):
    resp = await app_client.post(
        "/api/projects/00000000-0000-0000-0000-000000000000/pull-request",
        json={"title": "t", "confirm": True},
    )
    assert resp.status_code == 401


async def test_confirm_false_is_rejected(app_client, test_user):
    user_id, cookie = test_user
    project_id = await _make_project(user_id)
    try:
        resp = await app_client.post(
            f"/api/projects/{project_id}/pull-request",
            json={"title": "t", "confirm": False},
            cookies={"graphify_session": cookie},
        )
        assert resp.status_code == 400
        assert "confirmation is required" in resp.json()["detail"]
    finally:
        await _cleanup(project_id)


async def test_no_proposed_changes_is_rejected(app_client, test_user):
    user_id, cookie = test_user
    project_id = await _make_project(user_id)
    try:
        resp = await app_client.post(
            f"/api/projects/{project_id}/pull-request",
            json={"title": "t", "confirm": True},
            cookies={"graphify_session": cookie},
        )
        assert resp.status_code == 400
        assert "no proposed changes" in resp.json()["detail"]
    finally:
        await _cleanup(project_id)


async def test_missing_repo_token_returns_401(app_client, test_user, monkeypatch):
    user_id, cookie = test_user
    project_id = await _make_project(user_id, with_token=False)
    await _make_change(project_id)
    try:
        resp = await app_client.post(
            f"/api/projects/{project_id}/pull-request",
            json={"title": "t", "confirm": True},
            cookies={"graphify_session": cookie},
        )
        assert resp.status_code == 401
        assert "connect your github account" in resp.json()["detail"]
    finally:
        await _cleanup(project_id)


async def test_cannot_dispatch_pr_for_another_users_project(app_client, test_user):
    user_id, cookie = test_user
    other_project_id = uuid.uuid4()
    resp = await app_client.post(
        f"/api/projects/{other_project_id}/pull-request",
        json={"title": "t", "confirm": True},
        cookies={"graphify_session": cookie},
    )
    assert resp.status_code == 404


async def test_happy_path_commits_and_marks_changes_committed(app_client, test_user, monkeypatch):
    user_id, cookie = test_user
    project_id = await _make_project(user_id)
    change_id = await _make_change(project_id)

    _install_fake_client(
        monkeypatch,
        _fake_client(
            pr_result=PullRequestResult(number=9, url="https://github.com/o/r/pull/9", branch="graphify/agent-r-abc123")
        ),
    )

    try:
        resp = await app_client.post(
            f"/api/projects/{project_id}/pull-request",
            json={"title": "My change", "body": "desc", "confirm": True},
            cookies={"graphify_session": cookie},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["number"] == 9
        assert body["url"] == "https://github.com/o/r/pull/9"
        assert body["kind"] == "pull request"
        assert body["committed_files"] == ["a.py"]

        session_factory = get_session_factory()
        async with session_factory() as db:
            change = await db.get(ProjectAgentChange, change_id)
            assert change.status == ChangeStatus.COMMITTED
    finally:
        await _cleanup(project_id)


async def test_change_ids_filters_to_requested_subset(app_client, test_user, monkeypatch):
    user_id, cookie = test_user
    project_id = await _make_project(user_id)
    change_a = await _make_change(project_id, path="a.py")
    change_b = await _make_change(project_id, path="b.py")

    client = _fake_client()
    _install_fake_client(monkeypatch, client)

    try:
        resp = await app_client.post(
            f"/api/projects/{project_id}/pull-request",
            json={"title": "t", "confirm": True, "change_ids": [str(change_a)]},
            cookies={"graphify_session": cookie},
        )
        assert resp.status_code == 200
        assert resp.json()["committed_files"] == ["a.py"]

        session_factory = get_session_factory()
        async with session_factory() as db:
            a = await db.get(ProjectAgentChange, change_a)
            b = await db.get(ProjectAgentChange, change_b)
            assert a.status == ChangeStatus.COMMITTED
            assert b.status == ChangeStatus.PROPOSED
    finally:
        await _cleanup(project_id)


async def test_gitlab_project_uses_merge_request_wording(app_client, test_user, monkeypatch):
    user_id, cookie = test_user
    project_id = await _make_project(user_id, provider="gitlab")
    await _make_change(project_id)

    _install_fake_client(
        monkeypatch,
        _fake_client(pr_result=PullRequestResult(number=3, url="https://gitlab.com/o/r/-/merge_requests/3", branch="b")),
    )

    try:
        resp = await app_client.post(
            f"/api/projects/{project_id}/pull-request",
            json={"title": "t", "confirm": True},
            cookies={"graphify_session": cookie},
        )
        assert resp.status_code == 200
        assert resp.json()["kind"] == "merge request"
    finally:
        await _cleanup(project_id)


async def test_missing_repo_token_uses_merge_request_wording_for_gitlab(app_client, test_user):
    user_id, cookie = test_user
    project_id = await _make_project(user_id, provider="gitlab", with_token=False)
    await _make_change(project_id)
    try:
        resp = await app_client.post(
            f"/api/projects/{project_id}/pull-request",
            json={"title": "t", "confirm": True},
            cookies={"graphify_session": cookie},
        )
        assert resp.status_code == 401
        assert "merge request" in resp.json()["detail"]
    finally:
        await _cleanup(project_id)


async def test_branch_creation_conflict_returns_409_and_leaves_changes_proposed(
    app_client, test_user, monkeypatch
):
    user_id, cookie = test_user
    project_id = await _make_project(user_id)
    change_id = await _make_change(project_id)

    _install_fake_client(
        monkeypatch, _fake_client(branch_error=RepoConflictError("branch already exists"))
    )

    try:
        resp = await app_client.post(
            f"/api/projects/{project_id}/pull-request",
            json={"title": "t", "confirm": True},
            cookies={"graphify_session": cookie},
        )
        assert resp.status_code == 409

        session_factory = get_session_factory()
        async with session_factory() as db:
            change = await db.get(ProjectAgentChange, change_id)
            assert change.status == ChangeStatus.PROPOSED
    finally:
        await _cleanup(project_id)


async def test_commit_failure_after_branch_created_returns_502_and_leaves_changes_proposed(
    app_client, test_user, monkeypatch
):
    user_id, cookie = test_user
    project_id = await _make_project(user_id)
    change_id = await _make_change(project_id)

    _install_fake_client(monkeypatch, _fake_client(commit_error=RepoError("could not write blob")))

    try:
        resp = await app_client.post(
            f"/api/projects/{project_id}/pull-request",
            json={"title": "t", "confirm": True},
            cookies={"graphify_session": cookie},
        )
        assert resp.status_code == 502
        assert "was created and is safe to delete" not in resp.json()["detail"]
        assert "branch" in resp.json()["detail"]

        session_factory = get_session_factory()
        async with session_factory() as db:
            change = await db.get(ProjectAgentChange, change_id)
            assert change.status == ChangeStatus.PROPOSED
    finally:
        await _cleanup(project_id)


async def test_pr_open_failure_after_commit_returns_502_and_leaves_changes_proposed(
    app_client, test_user, monkeypatch
):
    user_id, cookie = test_user
    project_id = await _make_project(user_id)
    change_id = await _make_change(project_id)

    _install_fake_client(monkeypatch, _fake_client(pr_error=RepoError("provider rejected the request")))

    try:
        resp = await app_client.post(
            f"/api/projects/{project_id}/pull-request",
            json={"title": "t", "confirm": True},
            cookies={"graphify_session": cookie},
        )
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert "were committed to" in detail
        assert "could not be opened" in detail

        session_factory = get_session_factory()
        async with session_factory() as db:
            change = await db.get(ProjectAgentChange, change_id)
            assert change.status == ChangeStatus.PROPOSED
    finally:
        await _cleanup(project_id)
