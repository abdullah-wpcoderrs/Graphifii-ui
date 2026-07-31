"""Session-cookie and OAuth-state helpers.

Session cookie: itsdangerous-signed, carries only the user id, verified with
a max-age on every read (no server-side session store). OAuth state: a
random token set as a short-lived cookie by /api/auth/github/login and
compared against the callback's ?state= query param (double-submit pattern)
instead of a persisted store, since Phase 0/1 deliberately deferred Redis.
"""

from __future__ import annotations

import secrets
import uuid

from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.ext.asyncio import AsyncSession

from graphify.server.config import get_settings
from graphify.server.db import get_db
from graphify.server.models import User

SESSION_COOKIE_NAME = "graphify_session"
STATE_COOKIE_NAME = "graphify_oauth_state"

SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
STATE_MAX_AGE = 60 * 10  # 10 minutes

_SESSION_SALT = "graphify-session"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt=_SESSION_SALT)


def create_session_cookie_value(user_id: uuid.UUID) -> str:
    return _serializer().dumps({"user_id": str(user_id)})


def read_session_user_id(token: str) -> uuid.UUID | None:
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None

    raw_id = data.get("user_id")
    if not raw_id:
        return None
    try:
        return uuid.UUID(raw_id)
    except ValueError:
        return None


def generate_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def is_secure_cookie() -> bool:
    return get_settings().backend_url.startswith("https://")


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")

    user_id = read_session_user_id(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="session expired or invalid")

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")

    return user
