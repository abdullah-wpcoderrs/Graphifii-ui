"""Phase 2 — GitHub OAuth login/callback and session endpoints.

Contract (see graphify/docs/github-app-setup.md and
frontend/app/lib/auth-errors.ts):

    GET  /api/auth/github/login     -> redirect to GitHub's authorize URL
    GET  /api/auth/github/callback  -> redirect to FRONTEND_URL/dashboard on
                                        success, or FRONTEND_URL/auth/error
                                        with a known ?code= on failure
    GET  /api/session               -> current user, or 401
    POST /api/auth/logout           -> clears the session cookie
"""

from __future__ import annotations

import logging
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from graphify.server.config import get_settings
from graphify.server.crypto import encrypt
from graphify.server.db import get_db
from graphify.server.git_clients import (
    GitHubAuthError,
    GitHubUnavailableError,
    exchange_code_for_token,
    fetch_github_user,
)
from graphify.server.models import User
from graphify.server.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
    STATE_COOKIE_NAME,
    STATE_MAX_AGE,
    create_session_cookie_value,
    generate_oauth_state,
    get_current_user,
    is_secure_cookie,
)

logger = logging.getLogger("graphify.server.auth")

router = APIRouter(prefix="/api", tags=["auth"])

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"

AuthErrorCode = Literal[
    "access_denied", "invalid_state", "github_unavailable", "callback_failed"
]


def _callback_redirect_uri() -> str:
    return f"{get_settings().backend_url}/api/auth/github/callback"


def _error_redirect(code: AuthErrorCode, ref: str | None = None) -> RedirectResponse:
    frontend_url = get_settings().frontend_url
    query = {"code": code}
    if ref:
        query["ref"] = ref
    url = f"{frontend_url}/auth/error?{urllib.parse.urlencode(query)}"
    return RedirectResponse(url, status_code=302)


def _log_with_ref(message: str, exc: Exception | None = None) -> str:
    ref = secrets.token_hex(4)
    logger.error("%s (ref=%s)", message, ref, exc_info=exc)
    return ref


@router.get("/auth/github/login")
async def github_login() -> RedirectResponse:
    settings = get_settings()
    state = generate_oauth_state()

    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": _callback_redirect_uri(),
        "state": state,
    }
    authorize_url = f"{GITHUB_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    response = RedirectResponse(authorize_url, status_code=302)
    response.set_cookie(
        STATE_COOKIE_NAME,
        state,
        max_age=STATE_MAX_AGE,
        httponly=True,
        secure=is_secure_cookie(),
        samesite="lax",
        path="/api/auth/github",
    )
    return response


@router.get("/auth/github/callback")
async def github_callback(
    request: Request, db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    params = request.query_params

    if params.get("error"):
        return _error_redirect("access_denied")

    code = params.get("code")
    state = params.get("state")
    cookie_state = request.cookies.get(STATE_COOKIE_NAME)

    if not code or not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        return _error_redirect("invalid_state")

    try:
        token_data = await exchange_code_for_token(code, _callback_redirect_uri())
    except GitHubUnavailableError as exc:
        ref = _log_with_ref("GitHub unavailable during token exchange", exc)
        return _error_redirect("github_unavailable", ref)
    except GitHubAuthError as exc:
        ref = _log_with_ref("GitHub rejected the token exchange", exc)
        return _error_redirect("callback_failed", ref)

    try:
        profile = await fetch_github_user(token_data.access_token)
    except GitHubUnavailableError as exc:
        ref = _log_with_ref("GitHub unavailable fetching user profile", exc)
        return _error_redirect("github_unavailable", ref)
    except GitHubAuthError as exc:
        ref = _log_with_ref("GitHub rejected the user profile request", exc)
        return _error_redirect("callback_failed", ref)

    github_user_id = profile.get("id")
    if not github_user_id:
        ref = _log_with_ref("GitHub user profile missing id")
        return _error_redirect("callback_failed", ref)

    try:
        access_ciphertext, access_iv = encrypt(token_data.access_token)
        refresh_ciphertext, refresh_iv = (
            encrypt(token_data.refresh_token) if token_data.refresh_token else (None, None)
        )

        now = datetime.now(timezone.utc)
        access_expires_at = (
            now + timedelta(seconds=token_data.expires_in) if token_data.expires_in else None
        )
        refresh_expires_at = (
            now + timedelta(seconds=token_data.refresh_token_expires_in)
            if token_data.refresh_token_expires_in
            else None
        )

        result = await db.execute(select(User).where(User.github_user_id == github_user_id))
        user = result.scalar_one_or_none()

        if user is None:
            user = User(github_user_id=github_user_id)
            db.add(user)

        user.github_login = profile.get("login", user.github_login if user.github_login else "")
        user.email = profile.get("email")
        user.name = profile.get("name")
        user.avatar_url = profile.get("avatar_url")
        user.github_access_token_ciphertext = access_ciphertext
        user.github_access_token_iv = access_iv
        user.github_access_token_expires_at = access_expires_at
        user.github_refresh_token_ciphertext = refresh_ciphertext
        user.github_refresh_token_iv = refresh_iv
        user.github_refresh_token_expires_at = refresh_expires_at

        await db.commit()
        await db.refresh(user)
    except Exception as exc:  # noqa: BLE001 - convert any persistence failure into a safe redirect
        await db.rollback()
        ref = _log_with_ref("Failed to persist user after GitHub callback", exc)
        return _error_redirect("callback_failed", ref)

    response = RedirectResponse(f"{get_settings().frontend_url}/dashboard", status_code=302)
    response.delete_cookie(STATE_COOKIE_NAME, path="/api/auth/github")
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_cookie_value(user.id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=is_secure_cookie(),
        # The frontend (Vercel) and this API (Railway) are different sites in
        # production, so the session cookie must be readable on the frontend's
        # cross-site fetch() calls (e.g. GET /api/session). SameSite=Lax only
        # sends a cookie on top-level navigation — it would ride along on this
        # very redirect but then be silently withheld from every subsequent
        # XHR/fetch, making the frontend think the user was never logged in.
        # SameSite=None requires Secure, which is_secure_cookie() already
        # guarantees whenever backend_url is https.
        samesite="none",
        path="/",
    )
    return response


@router.get("/session")
async def get_session(user: User = Depends(get_current_user)) -> dict:
    return {
        "id": str(user.id),
        "githubLogin": user.github_login,
        "email": user.email,
        "name": user.name,
        "avatarUrl": user.avatar_url,
        "role": user.role.value,
    }


@router.post("/auth/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"ok": True}
