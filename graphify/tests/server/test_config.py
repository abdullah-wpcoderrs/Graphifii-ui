"""Tests for graphify/server/config.py — startup validation only, no DB/network.

These lock in the safety checks that make the admin/user session split
meaningful: if ADMIN_SESSION_SECRET is ever allowed to collide with the other
two secrets, the whole point of having a separate admin cookie silently
disappears (see admin_sessions.py's module docstring).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from graphify.server.config import Settings

_BASE_KWARGS = dict(
    frontend_url="http://localhost:3000",
    backend_url="http://localhost:8000",
    database_url="postgresql+psycopg://user:pw@host/db",
    session_secret="session-secret-value",
    token_encryption_key="token-encryption-key-value",
    github_app_id="1",
    github_client_id="client-id",
    github_client_secret="client-secret",
    github_private_key="-----BEGIN KEY-----\nbody\n-----END KEY-----",
    github_webhook_secret="webhook-secret",
)


def _settings(**overrides) -> Settings:
    """Build a Settings instance for these fields alone, with the real
    graphify/.env file excluded.

    Without `_env_file=None`, pydantic-settings still reads any field NOT
    passed here from the real .env on this machine — which, on a dev
    machine that has actually run this project, has real Railway ids, a
    real tunnel URL, and a real admin secret in it. A test asserting
    "falls back to a default when unset" would then silently pass or fail
    depending on what happens to be in that developer's .env, rather than
    testing the code. Confirmed by three tests failing exactly this way
    before this helper existed (2026-08-01).
    """
    return Settings(_env_file=None, **{**_BASE_KWARGS, **overrides})  # type: ignore[call-arg]


def test_session_secret_and_token_key_must_differ():
    with pytest.raises(ValidationError):
        _settings(token_encryption_key=_BASE_KWARGS["session_secret"])


@pytest.mark.parametrize("colliding_with", ["session_secret", "token_encryption_key"])
def test_admin_session_secret_rejects_reuse(colliding_with):
    with pytest.raises(ValidationError):
        _settings(admin_session_secret=_BASE_KWARGS[colliding_with])


def test_admin_session_secret_accepts_a_distinct_value():
    settings = _settings(admin_session_secret="a-third-distinct-secret")
    assert settings.admin_auth_configured is True


def test_admin_auth_configured_false_when_unset():
    settings = _settings()
    assert settings.admin_auth_configured is False


def test_railway_configured_requires_all_four_values():
    partial = _settings(railway_api_token="tok", railway_project_id="proj")
    assert partial.railway_configured is False

    full = _settings(
        railway_api_token="tok",
        railway_project_id="proj",
        railway_service_id="svc",
        railway_environment_id="env",
    )
    assert full.railway_configured is True


def test_callback_base_url_falls_back_to_backend_url():
    settings = _settings()
    assert settings.callback_base_url == "http://localhost:8000"


def test_callback_base_url_prefers_explicit_sandbox_override():
    settings = _settings(sandbox_callback_base_url="https://tunnel.example.com/")
    # Trailing slash stripped so callers can safely f-string a path onto it.
    assert settings.callback_base_url == "https://tunnel.example.com"


def test_github_private_key_rejects_truncated_pem():
    with pytest.raises(ValidationError):
        _settings(github_private_key="-----BEGIN KEY----- no newline")


@pytest.mark.parametrize("field", ["database_url", "session_secret", "github_client_id"])
def test_placeholder_values_are_rejected(field):
    with pytest.raises(ValidationError):
        _settings(**{field: "REPLACE_WITH_SOMETHING"})
