"""Pure-logic tests for graphify/server/token_refresh.py — no DB, no network.

Exercises get_valid_access_token's branching against fake User rows (plain
in-memory model instances, never persisted) and monkeypatched provider
refresh calls, covering: non-expiring/fresh token passthrough, successful
refresh + rotation persisted, expired-with-no-refresh-token, and
refresh-call-failure all falling back to None (the caller's existing 401
path). GitBucket is a plain decrypt with no refresh branch at all — see
GitBucketOAuthClient's docstring in git_clients.py for why.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from graphify.server import git_clients, token_refresh
from graphify.server.crypto import encrypt
from graphify.server.models import User


class _FakeDB:
    """Stands in for AsyncSession — only commit() is ever called."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _as_session(db: _FakeDB) -> AsyncSession:
    return cast(AsyncSession, db)


def _make_user(**overrides) -> User:
    user = User(id=uuid.uuid4(), github_user_id=1, github_login="octo")
    for key, value in overrides.items():
        setattr(user, key, value)
    return user


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


async def test_github_fresh_token_is_returned_without_refresh(monkeypatch):
    ciphertext, iv = encrypt("live-access-token")
    user = _make_user(
        github_access_token_ciphertext=ciphertext,
        github_access_token_iv=iv,
        github_access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    called = AsyncMock()
    monkeypatch.setattr(token_refresh, "refresh_github_token", called)

    token = await token_refresh.get_valid_access_token(user, "github", _as_session(_FakeDB()))

    assert token == "live-access-token"
    called.assert_not_called()


async def test_github_non_expiring_token_is_returned_without_refresh():
    ciphertext, iv = encrypt("non-expiring-token")
    user = _make_user(
        github_access_token_ciphertext=ciphertext,
        github_access_token_iv=iv,
        github_access_token_expires_at=None,
    )

    token = await token_refresh.get_valid_access_token(user, "github", _as_session(_FakeDB()))

    assert token == "non-expiring-token"


async def test_github_expired_token_is_refreshed_and_persisted(monkeypatch):
    old_access_ciphertext, old_access_iv = encrypt("stale-access-token")
    old_refresh_ciphertext, old_refresh_iv = encrypt("still-good-refresh-token")
    user = _make_user(
        github_access_token_ciphertext=old_access_ciphertext,
        github_access_token_iv=old_access_iv,
        github_access_token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        github_refresh_token_ciphertext=old_refresh_ciphertext,
        github_refresh_token_iv=old_refresh_iv,
    )

    new_token = git_clients.GitHubTokenResponse(
        access_token="fresh-access-token",
        refresh_token="rotated-refresh-token",
        expires_in=28800,
        refresh_token_expires_in=15897600,
    )
    seen_refresh_token = None

    async def fake_refresh(refresh_token: str):
        nonlocal seen_refresh_token
        seen_refresh_token = refresh_token
        return new_token

    monkeypatch.setattr(token_refresh, "refresh_github_token", fake_refresh)

    db = _FakeDB()
    token = await token_refresh.get_valid_access_token(user, "github", _as_session(db))

    assert token == "fresh-access-token"
    assert seen_refresh_token == "still-good-refresh-token"
    assert db.commits == 1
    # Rotated tokens are persisted back onto the user row, not just returned.
    assert user.github_access_token_ciphertext != old_access_ciphertext
    assert user.github_refresh_token_ciphertext != old_refresh_ciphertext
    assert user.github_access_token_expires_at is not None
    assert user.github_access_token_expires_at > datetime.now(timezone.utc)


async def test_github_expired_with_no_refresh_token_returns_none():
    ciphertext, iv = encrypt("stale-access-token")
    user = _make_user(
        github_access_token_ciphertext=ciphertext,
        github_access_token_iv=iv,
        github_access_token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        github_refresh_token_ciphertext=None,
        github_refresh_token_iv=None,
    )

    token = await token_refresh.get_valid_access_token(user, "github", _as_session(_FakeDB()))

    assert token is None


async def test_github_refresh_failure_returns_none_not_raise(monkeypatch):
    access_ciphertext, access_iv = encrypt("stale-access-token")
    refresh_ciphertext, refresh_iv = encrypt("revoked-refresh-token")
    user = _make_user(
        github_access_token_ciphertext=access_ciphertext,
        github_access_token_iv=access_iv,
        github_access_token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        github_refresh_token_ciphertext=refresh_ciphertext,
        github_refresh_token_iv=refresh_iv,
    )

    async def fake_refresh(refresh_token: str):
        raise git_clients.GitHubAuthError("refresh token revoked")

    monkeypatch.setattr(token_refresh, "refresh_github_token", fake_refresh)

    db = _FakeDB()
    token = await token_refresh.get_valid_access_token(user, "github", _as_session(db))

    assert token is None
    assert db.commits == 0


async def test_github_not_connected_returns_none():
    user = _make_user()
    token = await token_refresh.get_valid_access_token(user, "github", _as_session(_FakeDB()))
    assert token is None


# ---------------------------------------------------------------------------
# GitLab
# ---------------------------------------------------------------------------


async def test_gitlab_expired_token_is_refreshed_and_persisted(monkeypatch):
    monkeypatch.setenv("GITLAB_CLIENT_ID", "gid")
    monkeypatch.setenv("GITLAB_CLIENT_SECRET", "gsecret")
    token_refresh.get_settings.cache_clear()

    access_ciphertext, access_iv = encrypt("stale-gitlab-access")
    refresh_ciphertext, refresh_iv = encrypt("gitlab-refresh")
    user = _make_user(
        gitlab_access_token_ciphertext=access_ciphertext,
        gitlab_access_token_iv=access_iv,
        gitlab_access_token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        gitlab_refresh_token_ciphertext=refresh_ciphertext,
        gitlab_refresh_token_iv=refresh_iv,
    )

    new_token = git_clients.GitLabTokenResponse(
        access_token="fresh-gitlab-access",
        refresh_token="rotated-gitlab-refresh",
        expires_in=7200,
    )

    async def fake_refresh(self, refresh_token: str):
        assert refresh_token == "gitlab-refresh"
        return new_token

    monkeypatch.setattr(git_clients.GitLabOAuthClient, "refresh_access_token", fake_refresh)

    db = _FakeDB()
    try:
        token = await token_refresh.get_valid_access_token(user, "gitlab", _as_session(db))
    finally:
        token_refresh.get_settings.cache_clear()

    assert token == "fresh-gitlab-access"
    assert db.commits == 1
    assert user.gitlab_access_token_ciphertext != access_ciphertext
    assert user.gitlab_refresh_token_ciphertext != refresh_ciphertext


async def test_gitlab_not_configured_returns_none_instead_of_raising(monkeypatch):
    monkeypatch.delenv("GITLAB_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITLAB_CLIENT_SECRET", raising=False)
    token_refresh.get_settings.cache_clear()

    access_ciphertext, access_iv = encrypt("stale-gitlab-access")
    refresh_ciphertext, refresh_iv = encrypt("gitlab-refresh")
    user = _make_user(
        gitlab_access_token_ciphertext=access_ciphertext,
        gitlab_access_token_iv=access_iv,
        gitlab_access_token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        gitlab_refresh_token_ciphertext=refresh_ciphertext,
        gitlab_refresh_token_iv=refresh_iv,
    )

    try:
        token = await token_refresh.get_valid_access_token(user, "gitlab", _as_session(_FakeDB()))
    finally:
        token_refresh.get_settings.cache_clear()

    assert token is None


# ---------------------------------------------------------------------------
# GitBucket — no refresh flow exists, so this is a plain decrypt
# ---------------------------------------------------------------------------


async def test_gitbucket_returns_decrypted_token_even_with_an_old_expiry():
    ciphertext, iv = encrypt("gitbucket-token")
    user = _make_user(
        gitbucket_access_token_ciphertext=ciphertext,
        gitbucket_access_token_iv=iv,
        # GitBucketOAuthClient never sets this (see its docstring), but even
        # if something did, gitbucket has no refresh flow to attempt.
        gitbucket_access_token_expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    token = await token_refresh.get_valid_access_token(user, "gitbucket", _as_session(_FakeDB()))

    assert token == "gitbucket-token"


async def test_gitbucket_not_connected_returns_none():
    user = _make_user()
    token = await token_refresh.get_valid_access_token(user, "gitbucket", _as_session(_FakeDB()))
    assert token is None


async def test_unknown_provider_raises():
    user = _make_user()
    with pytest.raises(ValueError):
        await token_refresh.get_valid_access_token(user, "bitbucket", _as_session(_FakeDB()))
