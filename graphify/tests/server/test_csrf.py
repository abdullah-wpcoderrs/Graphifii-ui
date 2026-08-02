"""Unit tests for CSRFOriginMiddleware — no database, no full app import.

The real regression these guard against: SameSite=None on the session/admin
cookies (required because the frontend and API are different sites in
production) reopens the CSRF door that SameSite=Lax used to close, and this
app authenticates purely via cookies with no CSRF token. These tests build a
minimal ASGI app with just the middleware, since the routes that actually
carry these cookies are exercised only in database-backed tests that are
skipped without GRAPHIFY_TEST_DATABASE_URL — this coverage must not depend
on that.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from graphify.server.csrf import CSRFOriginMiddleware

FRONTEND_URL = "https://graphifii.vercel.app"
AUTH_COOKIE = "graphify_session"
OTHER_COOKIE = "graphify_admin_session"


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/safe")
    def safe() -> dict:
        return {"ok": True}

    @app.post("/unsafe")
    def unsafe() -> dict:
        return {"ok": True}

    app.add_middleware(
        CSRFOriginMiddleware,
        frontend_url=FRONTEND_URL,
        cookie_names=frozenset({AUTH_COOKIE, OTHER_COOKIE}),
    )
    return TestClient(app)


def test_same_origin_unsafe_request_with_cookie_is_allowed():
    response = _client().post(
        "/unsafe",
        cookies={AUTH_COOKIE: "token"},
        headers={"origin": FRONTEND_URL},
    )
    assert response.status_code == 200


def test_cross_site_unsafe_request_with_cookie_is_rejected():
    response = _client().post(
        "/unsafe",
        cookies={AUTH_COOKIE: "token"},
        headers={"origin": "https://evil.example.com"},
    )
    assert response.status_code == 403


def test_unsafe_request_with_cookie_and_no_origin_or_referer_is_rejected():
    # An attacker's cross-site form POST won't carry a same-origin Origin
    # header; a missing header must fail closed, not be treated as trusted.
    response = _client().post("/unsafe", cookies={AUTH_COOKIE: "token"})
    assert response.status_code == 403


def test_referer_is_used_when_origin_is_absent():
    response = _client().post(
        "/unsafe",
        cookies={AUTH_COOKIE: "token"},
        headers={"referer": f"{FRONTEND_URL}/dashboard"},
    )
    assert response.status_code == 200


def test_mismatched_referer_is_rejected():
    response = _client().post(
        "/unsafe",
        cookies={AUTH_COOKIE: "token"},
        headers={"referer": "https://evil.example.com/steal"},
    )
    assert response.status_code == 403


def test_unsafe_request_without_any_auth_cookie_is_not_checked():
    # No session/admin cookie present — e.g. an internal sandbox callback —
    # so this must pass through regardless of Origin.
    response = _client().post("/unsafe")
    assert response.status_code == 200


def test_admin_cookie_alone_also_triggers_the_check():
    response = _client().post(
        "/unsafe",
        cookies={OTHER_COOKIE: "token"},
        headers={"origin": "https://evil.example.com"},
    )
    assert response.status_code == 403


def test_safe_get_request_with_cookie_and_mismatched_origin_is_allowed():
    # GET/HEAD/OPTIONS are not state-changing; the middleware only guards
    # methods in _UNSAFE_METHODS.
    response = _client().get(
        "/safe",
        cookies={AUTH_COOKIE: "token"},
        headers={"origin": "https://evil.example.com"},
    )
    assert response.status_code == 200
