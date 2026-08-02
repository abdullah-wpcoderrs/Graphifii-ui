"""Tests for graphify/server/config.py — startup validation only, no DB/network.

These lock in the safety checks that make the admin/user session split
meaningful: if ADMIN_SESSION_SECRET is ever allowed to collide with the other
two secrets, the whole point of having a separate admin cookie silently
disappears (see admin_sessions.py's module docstring).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from graphify.server import config as config_module
from graphify.server.config import Settings, resolve_migration_database_url

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


def test_redis_queue_defaults_are_bounded_and_optional():
    settings = _settings()
    assert settings.redis_url is None
    assert settings.redis_run_queue_stream == "graphify:extraction-runs"
    assert settings.redis_run_queue_group == "graphify-dispatchers"
    assert settings.redis_run_queue_block_ms == 2_000
    assert settings.redis_run_queue_reclaim_seconds == 60


@pytest.mark.parametrize(
    "overrides",
    [
        {"redis_run_queue_block_ms": 50},
        {"redis_run_queue_reclaim_seconds": 10},
        {"redis_run_queue_max_length": 10},
    ],
)
def test_redis_queue_rejects_unsafe_bounds(overrides):
    with pytest.raises(ValidationError):
        _settings(**overrides)


def test_github_private_key_rejects_truncated_pem():
    with pytest.raises(ValidationError):
        _settings(github_private_key="-----BEGIN KEY----- no newline")


@pytest.mark.parametrize("field", ["database_url", "session_secret", "github_client_id"])
def test_placeholder_values_are_rejected(field):
    with pytest.raises(ValidationError):
        _settings(**{field: "REPLACE_WITH_SOMETHING"})


# --------------------------------------------------------------------------
# PEM normalization across environment loaders
# --------------------------------------------------------------------------
#
# The same .env line reaches the app in two different shapes depending on who
# parsed it: python-dotenv strips quotes and unescapes \n, Docker's env_file
# parser passes both through literally. Both must produce a usable key, or the
# app runs from a checkout and fails only once containerized.


def test_github_private_key_accepts_the_dotenv_shape():
    settings = _settings(github_private_key="-----BEGIN KEY-----\nbody\n-----END KEY-----")
    assert settings.github_private_key.startswith("-----BEGIN KEY-----\n")


def test_github_private_key_accepts_docker_env_file_escaped_newlines():
    # What a container actually receives from `env_file:` when .env holds a
    # quoted, backslash-escaped key.
    raw = '"-----BEGIN KEY-----\\nbody\\n-----END KEY-----"'

    settings = _settings(github_private_key=raw)

    assert "\n" in settings.github_private_key
    assert not settings.github_private_key.startswith('"')
    assert settings.github_private_key.endswith("-----END KEY-----")


def test_github_private_key_leaves_a_real_multiline_value_untouched():
    # Railway stores genuine multi-line values; normalization must not mangle
    # a key that was already correct.
    pem = "-----BEGIN KEY-----\nline1\nline2\n-----END KEY-----"
    assert _settings(github_private_key=pem).github_private_key == pem


def test_github_private_key_still_rejects_a_truly_truncated_pem():
    # Normalization must not turn the real failure mode into a silent pass.
    with pytest.raises(ValidationError):
        _settings(github_private_key='"-----BEGIN KEY----- no newline"')


def test_quoted_values_from_docker_env_file_are_unquoted():
    # `DATABASE_URL="postgresql+psycopg://..."` in .env: dotenv strips the
    # quotes, Docker's env_file parser does not. Without normalization the
    # container fails with "Could not parse SQLAlchemy URL", which points
    # nowhere near the real cause.
    settings = _settings(database_url='"postgresql+psycopg://u:p@h/db"')
    assert settings.database_url == "postgresql+psycopg://u:p@h/db"


def test_unquoted_values_are_left_exactly_as_they_are():
    settings = _settings(database_url="postgresql+psycopg://u:p@h/db")
    assert settings.database_url == "postgresql+psycopg://u:p@h/db"


def test_quotes_inside_a_value_are_preserved():
    # Only a matching leading/trailing pair is removed.
    secret = 'a"b"c-and-more-padding-to-32-bytes-long'
    assert _settings(session_secret=secret).session_secret == secret


def test_bare_postgres_scheme_is_upgraded_to_psycopg3():
    # Neon's console gives out `postgresql://`, which SQLAlchemy maps to
    # psycopg2 — never installed here. A checkout may survive on a
    # transitively present psycopg2; a container fails at engine creation.
    settings = _settings(database_url="postgresql://u:p@h/db?sslmode=require")
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_explicit_psycopg3_scheme_is_left_alone():
    url = "postgresql+psycopg://u:p@h/db"
    assert _settings(database_url=url).database_url == url


def test_an_explicit_other_driver_is_not_silently_rewritten():
    # Keep the error honest if someone genuinely selected another driver.
    url = "postgresql+asyncpg://u:p@h/db"
    assert _settings(database_url=url).database_url == url


def test_quoted_bare_scheme_is_both_unquoted_and_upgraded():
    # The combination that actually occurs in a Docker env_file.
    settings = _settings(database_url='"postgresql://u:p@h/db"')
    assert settings.database_url == "postgresql+psycopg://u:p@h/db"


def test_migration_url_prefers_the_bare_environment_variable():
    # SERVICE_ROLE=migrate promotes Neon's direct URL into DATABASE_URL for
    # that process only; it must win over Settings without ever building one.
    url = resolve_migration_database_url("postgresql://u:p@h/db")
    assert url == "postgresql+psycopg://u:p@h/db"


def test_migration_url_falls_back_to_settings_when_env_var_is_unset(monkeypatch):
    fallback = _settings(database_url="postgresql+psycopg://fallback/db")
    monkeypatch.setattr(config_module, "get_settings", lambda: fallback)

    assert resolve_migration_database_url(None) == fallback.database_url


def test_migration_url_falls_back_to_settings_when_env_var_is_whitespace_only(
    monkeypatch,
):
    # normalize_database_url() strips a whitespace-only value to "" — that
    # must not be handed to Alembic as sqlalchemy.url. Settings.database_url
    # is the correct fallback, exactly as when the variable is unset.
    fallback = _settings(database_url="postgresql+psycopg://fallback/db")
    monkeypatch.setattr(config_module, "get_settings", lambda: fallback)

    assert resolve_migration_database_url("   ") == fallback.database_url
