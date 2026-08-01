"""Integration tests for the isolated admin auth + credential routes,
against the real DB. See conftest.py for the real-DB / no-real-external-call
rationale.

POST /api/admin/credentials/verify's real branch (actually calling OpenAI/
Anthropic) is deliberately monkeypatched — this dev DB has a real configured
key, and a test suite must not spend real money or depend on a live
third-party API being reachable every time it runs.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete



# --- POST /api/admin/login ---------------------------------------------------


async def test_admin_login_succeeds_with_correct_credentials(app_client, test_admin):
    resp = await app_client.post(
        "/api/admin/login",
        json={"email": test_admin["email"], "password": test_admin["password"]},
    )
    assert resp.status_code == 200
    assert "graphify_admin_session" in resp.cookies


async def test_admin_login_rejects_wrong_password(app_client, test_admin):
    resp = await app_client.post(
        "/api/admin/login",
        json={"email": test_admin["email"], "password": "definitely-not-it"},
    )
    assert resp.status_code == 401


async def test_admin_login_unknown_email_and_wrong_password_return_identical_bodies(app_client, test_admin):
    """The response for "no such admin" and "wrong password" must be
    byte-identical, or the endpoint becomes an email-enumeration oracle."""
    wrong_password_resp = await app_client.post(
        "/api/admin/login",
        json={"email": test_admin["email"], "password": "definitely-not-it"},
    )
    unknown_email_resp = await app_client.post(
        "/api/admin/login",
        json={"email": f"{uuid.uuid4().hex}@example.com", "password": "definitely-not-it"},
    )
    assert wrong_password_resp.status_code == unknown_email_resp.status_code == 401
    assert wrong_password_resp.json() == unknown_email_resp.json()


async def test_admin_login_locks_out_after_five_failed_attempts(app_client, test_admin):
    for _ in range(5):
        resp = await app_client.post(
            "/api/admin/login",
            json={"email": test_admin["email"], "password": "wrong"},
        )
        assert resp.status_code == 401

    locked_resp = await app_client.post(
        "/api/admin/login",
        json={"email": test_admin["email"], "password": "wrong"},
    )
    assert locked_resp.status_code == 429


# --- isolation: admin cookie must never work as a user cookie, or vice versa -


async def test_admin_cookie_is_rejected_on_a_user_route(app_client, test_admin):
    login_resp = await app_client.post(
        "/api/admin/login",
        json={"email": test_admin["email"], "password": test_admin["password"]},
    )
    admin_cookie = login_resp.cookies["graphify_admin_session"]

    resp = await app_client.get("/api/session", cookies={"graphify_session": admin_cookie})
    assert resp.status_code == 401


async def test_admin_cookie_is_rejected_on_admin_data_routes_without_login(app_client):
    resp = await app_client.get("/api/admin/credentials")
    assert resp.status_code == 401


async def test_user_session_cookie_is_rejected_on_admin_routes(app_client, test_user):
    _, user_cookie = test_user
    resp = await app_client.get(
        "/api/admin/credentials", cookies={"graphify_admin_session": user_cookie}
    )
    assert resp.status_code == 401


# --- GET /api/admin/me -------------------------------------------------------


async def test_admin_me_returns_the_logged_in_admin(app_client, test_admin):
    login_resp = await app_client.post(
        "/api/admin/login",
        json={"email": test_admin["email"], "password": test_admin["password"]},
    )
    admin_cookie = login_resp.cookies["graphify_admin_session"]

    resp = await app_client.get("/api/admin/me", cookies={"graphify_admin_session": admin_cookie})
    assert resp.status_code == 200
    assert resp.json()["email"] == test_admin["email"]


# --- credential verify: never a real outbound call in tests -----------------


async def test_verify_credential_reports_not_configured_without_touching_real_data(
    app_client, test_admin, monkeypatch
):
    """Monkeypatched to return "no credential" rather than deleting the
    real SystemCredential row this dev DB has configured."""
    from graphify.server.routes import admin as admin_module

    async def _no_credential(provider, db):
        return None

    monkeypatch.setattr(admin_module, "_get_credential", _no_credential)

    login_resp = await app_client.post(
        "/api/admin/login",
        json={"email": test_admin["email"], "password": test_admin["password"]},
    )
    admin_cookie = login_resp.cookies["graphify_admin_session"]

    resp = await app_client.post(
        "/api/admin/credentials/verify",
        json={"provider": "openai"},
        cookies={"graphify_admin_session": admin_cookie},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


async def test_verify_credential_records_usage_from_a_faked_provider_response(
    app_client, test_admin, monkeypatch
):
    """Proves the usage-recording wiring (the actual point of this test)
    without ever calling a real provider: fakes both the stored credential
    lookup and the HTTP call, but lets record_usage() run for real against
    the real DB, then confirms the row landed and cleans it up."""
    import httpx
    from sqlalchemy import select

    from graphify.server.crypto import encrypt
    from graphify.server.models import SystemCredential, UsageEvent
    from graphify.server.routes import admin as admin_module

    ciphertext, iv = encrypt("fake-test-key-never-sent-anywhere")
    fake_credential = SystemCredential(
        provider="openai", key_ciphertext=ciphertext, key_iv=iv, model="gpt-4.1-mini"
    )

    async def _fake_get_credential(provider, db):
        return fake_credential

    async def _fake_openai_call(base_url, model, api_key):
        return httpx.Response(
            200,
            json={"usage": {"prompt_tokens": 42, "completion_tokens": 7}},
            request=httpx.Request("POST", "https://example.invalid"),
        )

    monkeypatch.setattr(admin_module, "_get_credential", _fake_get_credential)
    monkeypatch.setattr(admin_module, "_call_openai_compat", _fake_openai_call)

    login_resp = await app_client.post(
        "/api/admin/login",
        json={"email": test_admin["email"], "password": test_admin["password"]},
    )
    admin_cookie = login_resp.cookies["graphify_admin_session"]

    resp = await app_client.post(
        "/api/admin/credentials/verify",
        json={"provider": "openai"},
        cookies={"graphify_admin_session": admin_cookie},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    from graphify.server.db import get_session_factory

    session_factory = get_session_factory()
    async with session_factory() as db:
        event = (
            await db.execute(
                select(UsageEvent)
                .where(UsageEvent.operation == "verify", UsageEvent.prompt_tokens == 42)
                .order_by(UsageEvent.created_at.desc())
            )
        ).scalars().first()
        try:
            assert event is not None
            assert event.completion_tokens == 7
        finally:
            if event is not None:
                await db.delete(event)
                await db.commit()
