"""Tests for graphify/server/admin_sessions.py — no DB, no network.

The property that matters most here is isolation: an admin cookie must never
be usable as a user cookie, and vice versa, even though both are built with
the same library (itsdangerous) in the same process. That isolation rests on
three independent differences (secret, salt, cookie name) — this file proves
all three hold, not just one.
"""
from __future__ import annotations

import uuid

import pytest

from graphify.server import admin_sessions as admin_mod
from graphify.server import sessions as user_mod
from graphify.server.config import get_settings


@pytest.fixture(autouse=True)
def _admin_secret(monkeypatch):
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-admin-secret-distinct-from-others")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_password_hash_is_never_the_plaintext():
    hashed = admin_mod.hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2")
    assert "correct horse" not in hashed


def test_password_verify_round_trip():
    hashed = admin_mod.hash_password("correct horse battery staple")
    assert admin_mod.verify_password("correct horse battery staple", hashed) is True
    assert admin_mod.verify_password("wrong password", hashed) is False


def test_verify_password_never_raises_on_garbage_hash():
    # A hand-edited or corrupted DB row must fail login, not 500 the endpoint.
    assert admin_mod.verify_password("anything", "not-a-real-argon2-hash") is False


def test_admin_cookie_round_trips():
    admin_id = uuid.uuid4()
    token = admin_mod.create_admin_session_cookie_value(admin_id)
    assert admin_mod.read_admin_session_id(token) == admin_id


def test_tampered_admin_cookie_is_rejected():
    token = admin_mod.create_admin_session_cookie_value(uuid.uuid4())
    tampered = token[:-4] + "AAAA"
    assert admin_mod.read_admin_session_id(tampered) is None


def test_admin_cookie_is_rejected_by_the_user_session_reader():
    """An admin who somehow got their cookie into the user cookie slot must
    not gain user access — proves the secret+salt difference matters, not
    just the cookie name."""
    token = admin_mod.create_admin_session_cookie_value(uuid.uuid4())
    assert user_mod.read_session_user_id(token) is None


def test_user_cookie_is_rejected_by_the_admin_session_reader():
    token = user_mod.create_session_cookie_value(uuid.uuid4())
    assert admin_mod.read_admin_session_id(token) is None


def test_cookie_names_are_distinct():
    assert admin_mod.ADMIN_SESSION_COOKIE_NAME != user_mod.SESSION_COOKIE_NAME


def test_missing_admin_secret_raises_service_unavailable(monkeypatch):
    """Deployments that haven't run seed-admin/set the secret yet must get a
    clear 503, not a confusing crash deep inside itsdangerous.

    Patches admin_sessions.get_settings directly rather than unsetting the
    env var: the real graphify/.env on this machine has ADMIN_SESSION_SECRET
    set for actual dev use, so an env-var-only approach would silently fall
    back to that real value via pydantic-settings' env_file loading and test
    the wrong thing.
    """
    from fastapi import HTTPException

    class _StubSettings:
        admin_session_secret = None

    monkeypatch.setattr(admin_mod, "get_settings", lambda: _StubSettings())

    with pytest.raises(HTTPException) as exc_info:
        admin_mod.create_admin_session_cookie_value(uuid.uuid4())
    assert exc_info.value.status_code == 503
