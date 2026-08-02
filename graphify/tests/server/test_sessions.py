"""Tests for graphify/server/sessions.py's cookie-security helpers — no DB.

session_cookie_samesite() must never return "none" when is_secure_cookie()
is false: a browser silently drops a SameSite=None cookie lacking Secure,
which would break login outright in local HTTP development.
"""
from __future__ import annotations

import pytest

from graphify.server import sessions
from graphify.server.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_samesite_is_none_when_backend_is_https(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", "https://graphify-api-production.up.railway.app")
    get_settings.cache_clear()

    assert sessions.is_secure_cookie() is True
    assert sessions.session_cookie_samesite() == "none"


def test_samesite_falls_back_to_lax_when_backend_is_http(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", "http://localhost:8000")
    get_settings.cache_clear()

    assert sessions.is_secure_cookie() is False
    assert sessions.session_cookie_samesite() == "lax"
