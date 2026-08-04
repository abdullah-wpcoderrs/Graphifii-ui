"""Tests for the repository-list cache in graphify/server/routes/github.py.

Calls list_repositories() directly with a fake user and a monkeypatched
httpx.AsyncClient/get_valid_access_token, the same style test_token_refresh.py
uses to exercise outbound-call routes without a live GitHub connection or a
full FastAPI TestClient.

The cache exists because every load of the Repositories page used to hit
GitHub live and took 2-3 seconds, measured, on every single request — these
pin the fix: a second request within the TTL must not call GitHub again, a
failed request must never poison the cache with bad data, and users must
never see each other's cached repos.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from graphify.server.routes import github as github_module


class _FakeUser:
    def __init__(self, user_id: uuid.UUID | None = None) -> None:
        self.id = user_id or uuid.uuid4()


class _FakeResponse:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient so tests can assert call count."""

    calls = 0
    response: _FakeResponse

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, *args, **kwargs):
        type(self).calls += 1
        return type(self).response


def _sample_repo(repo_id: int = 1) -> dict:
    return {
        "id": repo_id,
        "name": "repo",
        "full_name": "user/repo",
        "html_url": "https://github.com/user/repo",
        "default_branch": "main",
        "owner": {"login": "user", "type": "User"},
    }


@pytest.fixture(autouse=True)
def _isolated_cache_and_client(monkeypatch):
    github_module._repo_cache.clear()
    _FakeAsyncClient.calls = 0
    _FakeAsyncClient.response = _FakeResponse(200, [_sample_repo()])
    monkeypatch.setattr(github_module.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(
        github_module, "get_valid_access_token", AsyncMock(return_value="a-token")
    )
    yield
    github_module._repo_cache.clear()


async def test_second_call_within_ttl_is_served_from_cache():
    user = _FakeUser()

    first = await github_module.list_repositories(user=user, db=None)
    second = await github_module.list_repositories(user=user, db=None)

    assert first == second
    assert _FakeAsyncClient.calls == 1


async def test_different_users_do_not_share_a_cache_entry():
    await github_module.list_repositories(user=_FakeUser(), db=None)
    await github_module.list_repositories(user=_FakeUser(), db=None)

    assert _FakeAsyncClient.calls == 2


async def test_cache_expires_after_ttl(monkeypatch):
    user = _FakeUser()

    await github_module.list_repositories(user=user, db=None)
    assert _FakeAsyncClient.calls == 1

    # Jump the cache's own clock rather than sleeping the test suite for 60s.
    real_monotonic = github_module.time.monotonic()
    monkeypatch.setattr(
        github_module.time,
        "monotonic",
        lambda: real_monotonic + github_module._REPO_CACHE_TTL_SECONDS + 1,
    )

    await github_module.list_repositories(user=user, db=None)
    assert _FakeAsyncClient.calls == 2


async def test_a_failed_github_call_is_not_cached():
    _FakeAsyncClient.response = _FakeResponse(502, {})
    user = _FakeUser()

    with pytest.raises(HTTPException):
        await github_module.list_repositories(user=user, db=None)

    _FakeAsyncClient.response = _FakeResponse(200, [_sample_repo(repo_id=2)])
    result = await github_module.list_repositories(user=user, db=None)

    # Two real calls (the failure was never cached) and the fresh data wins.
    assert _FakeAsyncClient.calls == 2
    assert result[0]["id"] == 2


async def test_cache_hit_does_not_call_get_valid_access_token():
    # A cached response should short-circuit before touching the token at
    # all — otherwise a cache hit still pays for a (cheaper, but real)
    # refresh-check round trip.
    user = _FakeUser()
    await github_module.list_repositories(user=user, db=None)

    github_module.get_valid_access_token.reset_mock()
    await github_module.list_repositories(user=user, db=None)

    github_module.get_valid_access_token.assert_not_called()
