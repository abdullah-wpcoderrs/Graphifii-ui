"""Phase 3 — GitLab/GitBucket integration status, OAuth flows, and repo listing.

Follows the same double-submit-cookie OAuth state pattern as
routes/auth.py's GitHub flow (see graphify/graphify/server/sessions.py),
parameterized per provider so a GitLab flow in progress doesn't collide
with a simultaneous GitBucket one.
"""

from __future__ import annotations

import logging
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from graphify.server.config import get_settings
from graphify.server.crypto import encrypt
from graphify.server.db import get_db
from graphify.server.git_clients import (
    GitBucketAuthError,
    GitBucketOAuthClient,
    GitBucketUnavailableError,
    GitLabAuthError,
    GitLabOAuthClient,
    GitLabUnavailableError,
)
from graphify.server.models import User
from graphify.server.sessions import (
    SESSION_COOKIE_NAME,
    STATE_MAX_AGE,
    generate_oauth_state,
    get_current_user,
    is_secure_cookie,
    read_session_user_id,
)
from graphify.server.token_refresh import get_valid_access_token

logger = logging.getLogger("graphify.server.integrations")

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

Provider = Literal["gitlab", "gitbucket"]
_PROVIDERS: tuple[Provider, ...] = ("gitlab", "gitbucket")
_TIMEOUT = 10.0

GITLAB_AUTHORIZE_URL = "https://gitlab.com/oauth/authorize"
GITLAB_PROJECTS_URL = "https://gitlab.com/api/v4/projects"


def _state_cookie_name(provider: str) -> str:
    return f"graphify_oauth_state_{provider}"


def _validate_provider(provider: str) -> Provider:
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail="unknown integration provider")
    return provider  # type: ignore[return-value]


def _callback_redirect_uri(provider: Provider) -> str:
    return f"{get_settings().backend_url}/api/integrations/{provider}/callback"


def _error_redirect(ref: str | None = None) -> RedirectResponse:
    frontend_url = get_settings().frontend_url
    query = {"code": "integration_connection_failed"}
    if ref:
        query["ref"] = ref
    return RedirectResponse(f"{frontend_url}/auth/error?{urllib.parse.urlencode(query)}", status_code=302)


def _log_with_ref(message: str, exc: Exception | None = None) -> str:
    ref = secrets.token_hex(4)
    logger.error("%s (ref=%s)", message, ref, exc_info=exc)
    return ref


def _gitlab_client() -> GitLabOAuthClient | None:
    settings = get_settings()
    if not settings.gitlab_configured:
        return None
    return GitLabOAuthClient(settings.gitlab_client_id, settings.gitlab_client_secret)  # type: ignore[arg-type]


def _gitbucket_client() -> GitBucketOAuthClient | None:
    settings = get_settings()
    if not settings.gitbucket_configured:
        return None
    return GitBucketOAuthClient(
        settings.gitbucket_instance_url,  # type: ignore[arg-type]
        settings.gitbucket_client_id,  # type: ignore[arg-type]
        settings.gitbucket_client_secret,  # type: ignore[arg-type]
    )


@router.get("")
async def list_integrations(user: User = Depends(get_current_user)) -> list[dict]:
    settings = get_settings()

    integrations: list[dict] = [
        {
            "id": "github",
            "name": "GitHub",
            "icon": "github",
            "status": "connected" if user.github_access_token_ciphertext else "not_connected",
            "login": user.github_login,
        }
    ]

    if settings.gitlab_configured:
        integrations.append(
            {
                "id": "gitlab",
                "name": "GitLab",
                "icon": "gitlab",
                "status": "connected" if user.gitlab_access_token_ciphertext else "not_connected",
                "login": user.gitlab_login,
            }
        )
    else:
        integrations.append(
            {
                "id": "gitlab",
                "name": "GitLab",
                "icon": "gitlab",
                "status": "not_configured",
                "login": None,
                "message": "Admin has not configured GitLab OAuth (missing GITLAB_CLIENT_ID)",
            }
        )

    if settings.gitbucket_configured:
        integrations.append(
            {
                "id": "gitbucket",
                "name": "GitBucket",
                "icon": "gitbucket",
                "status": "connected" if user.gitbucket_access_token_ciphertext else "not_connected",
                "login": user.gitbucket_login,
            }
        )
    else:
        integrations.append(
            {
                "id": "gitbucket",
                "name": "GitBucket",
                "icon": "gitbucket",
                "status": "not_configured",
                "login": None,
                "message": "Admin has not configured GitBucket OAuth",
            }
        )

    return integrations


@router.get("/{provider}/login")
async def integration_login(provider: str) -> RedirectResponse:
    provider = _validate_provider(provider)
    settings = get_settings()

    if provider == "gitlab":
        if not settings.gitlab_configured:
            raise HTTPException(status_code=400, detail="GitLab is not configured by the administrator")
        state = generate_oauth_state()
        params = {
            "client_id": settings.gitlab_client_id,
            "redirect_uri": _callback_redirect_uri(provider),
            "state": state,
            "response_type": "code",
            "scope": "read_api read_user",
        }
        authorize_url = f"{GITLAB_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    else:
        if not settings.gitbucket_configured:
            raise HTTPException(status_code=400, detail="GitBucket is not configured by the administrator")
        state = generate_oauth_state()
        params = {
            "client_id": settings.gitbucket_client_id,
            "redirect_uri": _callback_redirect_uri(provider),
            "state": state,
        }
        authorize_url = (
            f"{settings.gitbucket_instance_url.rstrip('/')}/login/oauth/authorize?"  # type: ignore[union-attr]
            f"{urllib.parse.urlencode(params)}"
        )

    response = RedirectResponse(authorize_url, status_code=302)
    response.set_cookie(
        _state_cookie_name(provider),
        state,
        max_age=STATE_MAX_AGE,
        httponly=True,
        secure=is_secure_cookie(),
        samesite="lax",
        path=f"/api/integrations/{provider}",
    )
    return response


@router.get("/{provider}/callback")
async def integration_callback(
    provider: str, request: Request, db: AsyncSession = Depends(get_db)
) -> RedirectResponse:
    provider = _validate_provider(provider)
    params = request.query_params

    if params.get("error"):
        return _error_redirect()

    code = params.get("code")
    state = params.get("state")
    cookie_state = request.cookies.get(_state_cookie_name(provider))

    if not code or not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        return _error_redirect()

    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return _error_redirect()

    user_id = read_session_user_id(token)
    if user_id is None:
        return _error_redirect()

    user = await db.get(User, user_id)
    if user is None:
        return _error_redirect()

    try:
        if provider == "gitlab":
            client = _gitlab_client()
            if client is None:
                return _error_redirect()
            token_data = await client.exchange_code_for_token(code, _callback_redirect_uri(provider))
            profile = await client.fetch_gitlab_user(token_data.access_token)
            access_ciphertext, access_iv = encrypt(token_data.access_token)
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=token_data.expires_in)
                if token_data.expires_in
                else None
            )
            user.gitlab_access_token_ciphertext = access_ciphertext
            user.gitlab_access_token_iv = access_iv
            user.gitlab_access_token_expires_at = expires_at
            # Phase 5 fix: this was previously dropped on the floor despite
            # the model having columns for it since Phase 3, which meant
            # refresh rotation could never work for GitLab no matter what
            # token_refresh.py did — there was nothing to refresh with.
            if token_data.refresh_token:
                refresh_ciphertext, refresh_iv = encrypt(token_data.refresh_token)
                user.gitlab_refresh_token_ciphertext = refresh_ciphertext
                user.gitlab_refresh_token_iv = refresh_iv
            else:
                user.gitlab_refresh_token_ciphertext = None
                user.gitlab_refresh_token_iv = None
            user.gitlab_user_id = profile.get("id")
            user.gitlab_login = profile.get("username")
        else:
            client = _gitbucket_client()
            if client is None:
                return _error_redirect()
            token_data = await client.exchange_code_for_token(code, _callback_redirect_uri(provider))
            profile = await client.fetch_gitbucket_user(token_data.access_token)
            access_ciphertext, access_iv = encrypt(token_data.access_token)
            user.gitbucket_access_token_ciphertext = access_ciphertext
            user.gitbucket_access_token_iv = access_iv
            user.gitbucket_user_id = profile.get("id")
            user.gitbucket_login = profile.get("login")

        await db.commit()
    except (GitLabUnavailableError, GitBucketUnavailableError) as exc:
        await db.rollback()
        ref = _log_with_ref(f"{provider} unavailable during OAuth callback", exc)
        return _error_redirect(ref)
    except (GitLabAuthError, GitBucketAuthError) as exc:
        await db.rollback()
        ref = _log_with_ref(f"{provider} rejected the OAuth callback", exc)
        return _error_redirect(ref)
    except Exception as exc:  # noqa: BLE001 - convert any persistence failure into a safe redirect
        await db.rollback()
        ref = _log_with_ref(f"Failed to persist {provider} integration", exc)
        return _error_redirect(ref)

    frontend_url = get_settings().frontend_url
    query = urllib.parse.urlencode({"provider": provider, "status": "success"})
    response = RedirectResponse(f"{frontend_url}/integrations?{query}", status_code=302)
    response.delete_cookie(_state_cookie_name(provider), path=f"/api/integrations/{provider}")
    return response


@router.post("/{provider}/disconnect")
async def disconnect_integration(
    provider: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    provider = _validate_provider(provider)

    if provider == "gitlab":
        user.gitlab_access_token_ciphertext = None
        user.gitlab_access_token_iv = None
        user.gitlab_access_token_expires_at = None
        user.gitlab_refresh_token_ciphertext = None
        user.gitlab_refresh_token_iv = None
        user.gitlab_user_id = None
        user.gitlab_login = None
    else:
        user.gitbucket_access_token_ciphertext = None
        user.gitbucket_access_token_iv = None
        user.gitbucket_access_token_expires_at = None
        user.gitbucket_user_id = None
        user.gitbucket_login = None

    await db.commit()
    return {"ok": True}


@router.get("/{provider}/repos")
async def list_integration_repos(
    provider: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    provider = _validate_provider(provider)

    if provider == "gitlab":
        access_token = await get_valid_access_token(user, "gitlab", db)
        if access_token is None:
            raise HTTPException(status_code=401, detail="GitLab connection expired, please reconnect")
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                response = await client.get(
                    GITLAB_PROJECTS_URL,
                    params={"owned": "true", "per_page": 100},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=502, detail=f"GitLab request failed: {exc}") from exc
        if response.status_code == 401:
            raise HTTPException(status_code=401, detail="GitLab connection expired, please reconnect")
        if response.status_code != 200:
            raise HTTPException(status_code=502, detail=f"GitLab returned {response.status_code}")
        return [
            {
                "id": p["id"],
                "name": p["name"],
                "full_name": p["path_with_namespace"],
                "html_url": p["web_url"],
                "description": p.get("description"),
                "default_branch": p.get("default_branch", "main"),
                "private": p.get("visibility") != "public",
                "language": None,  # GitLab's project list endpoint doesn't include a primary language
                "pushed_at": p.get("last_activity_at"),
                "owner_login": (p.get("namespace") or {}).get("path"),
                "owner_type": "Organization" if (p.get("namespace") or {}).get("kind") == "group" else "User",
            }
            for p in response.json()
        ]

    settings = get_settings()
    if not settings.gitbucket_configured:
        raise HTTPException(status_code=400, detail="GitBucket is not configured by the administrator")
    access_token = await get_valid_access_token(user, "gitbucket", db)
    if access_token is None:
        raise HTTPException(status_code=401, detail="GitBucket not connected")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            response = await client.get(
                f"{settings.gitbucket_instance_url.rstrip('/')}/api/v3/user/repos",  # type: ignore[union-attr]
                headers={"Authorization": f"token {access_token}"},
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"GitBucket request failed: {exc}") from exc
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="GitBucket connection expired, please reconnect")
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"GitBucket returned {response.status_code}")
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "full_name": r["full_name"],
            "html_url": r["html_url"],
            "description": r.get("description"),
            "default_branch": r.get("default_branch", "main"),
            "private": r.get("private", False),
            "language": r.get("language"),
            "pushed_at": r.get("pushed_at"),
            "owner_login": (r.get("owner") or {}).get("login"),
            "owner_type": (r.get("owner") or {}).get("type", "User"),
        }
        for r in response.json()
    ]
