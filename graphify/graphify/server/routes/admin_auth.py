"""Phase 4 — admin email/password login, isolated from the GitHub OAuth flow.

Unlike /api/auth/github/*, this endpoint accepts a password directly and is
therefore brute-forceable, so it carries protections the OAuth routes do not
need: a per-email+IP attempt limiter, a uniform error response that never
distinguishes "no such email" from "wrong password", and a dummy hash
verification on the unknown-email path so response timing does not leak
which emails exist.

The rate limiter is in-process (a plain dict). That is honest for a
single-instance deployment and is not sufficient across replicas — if this
service is ever horizontally scaled, this needs to move to Redis or the
database. Documented rather than silently assumed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from graphify.server.admin_sessions import (
    ADMIN_SESSION_COOKIE_NAME,
    ADMIN_SESSION_MAX_AGE,
    create_admin_session_cookie_value,
    get_current_admin,
    hash_password,
    needs_rehash,
    verify_password,
)
from graphify.server.config import get_settings
from graphify.server.db import get_db
from graphify.server.models import Admin
from graphify.server.sessions import is_secure_cookie

logger = logging.getLogger("graphify.server.admin_auth")

router = APIRouter(prefix="/api/admin", tags=["admin-auth"])

MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60
ATTEMPT_WINDOW_SECONDS = 15 * 60

# Verified against on the unknown-email path purely to burn the same ~50ms
# argon2 does on a real account, so login timing cannot be used to enumerate
# admin emails. The password is irrelevant and never matches anything.
_DUMMY_HASH = hash_password("graphify-timing-equalizer")

_GENERIC_LOGIN_ERROR = "Invalid email or password"


@dataclass
class _Attempts:
    count: int = 0
    first_at: float = field(default_factory=time.monotonic)
    locked_until: float = 0.0


_attempts: dict[str, _Attempts] = {}


def _attempt_key(email: str, request: Request) -> str:
    client_host = request.client.host if request.client else "unknown"
    return f"{email.lower()}|{client_host}"


def _check_not_locked(key: str) -> None:
    record = _attempts.get(key)
    if record is None:
        return

    now = time.monotonic()
    if record.locked_until > now:
        retry_after = int(record.locked_until - now)
        raise HTTPException(
            status_code=429,
            detail="too many failed login attempts, try again later",
            headers={"Retry-After": str(retry_after)},
        )

    # Window elapsed (or lockout served) — start counting fresh.
    if record.locked_until or now - record.first_at > ATTEMPT_WINDOW_SECONDS:
        _attempts.pop(key, None)


def _record_failure(key: str) -> None:
    now = time.monotonic()
    record = _attempts.setdefault(key, _Attempts())
    record.count += 1
    if record.count >= MAX_ATTEMPTS:
        record.locked_until = now + LOCKOUT_SECONDS


def _clear_attempts(key: str) -> None:
    _attempts.pop(key, None)


class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
async def admin_login(
    payload: AdminLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = get_settings()
    if not settings.admin_auth_configured:
        raise HTTPException(
            status_code=503,
            detail="admin authentication is not configured (ADMIN_SESSION_SECRET unset)",
        )

    key = _attempt_key(payload.email, request)
    _check_not_locked(key)

    result = await db.execute(select(Admin).where(Admin.email == payload.email.lower()))
    admin = result.scalar_one_or_none()

    if admin is None:
        # Spend the same time as a real verify, then fail identically.
        verify_password(payload.password, _DUMMY_HASH)
        _record_failure(key)
        logger.warning("admin login failed (unknown email) from %s", request.client.host if request.client else "?")
        raise HTTPException(status_code=401, detail=_GENERIC_LOGIN_ERROR)

    if not verify_password(payload.password, admin.password_hash):
        _record_failure(key)
        logger.warning("admin login failed (bad password) for admin id %s", admin.id)
        raise HTTPException(status_code=401, detail=_GENERIC_LOGIN_ERROR)

    if not admin.is_active:
        # Same generic message: whether an account is disabled is not
        # something an unauthenticated caller should be able to probe.
        _record_failure(key)
        raise HTTPException(status_code=401, detail=_GENERIC_LOGIN_ERROR)

    _clear_attempts(key)

    # Opportunistically upgrade the stored hash if argon2's parameters have
    # moved on since this password was set.
    if needs_rehash(admin.password_hash):
        admin.password_hash = hash_password(payload.password)

    admin.last_login_at = func.now()
    await db.commit()

    response.set_cookie(
        ADMIN_SESSION_COOKIE_NAME,
        create_admin_session_cookie_value(admin.id),
        max_age=ADMIN_SESSION_MAX_AGE,
        httponly=True,
        secure=is_secure_cookie(),
        # See the matching comment on the GitHub session cookie in auth.py:
        # this endpoint is called via cross-site fetch() from the deployed
        # frontend, so SameSite must be None (with Secure, already guaranteed
        # by is_secure_cookie() in production) or the cookie is set but never
        # sent back on the next admin API call.
        samesite="none",
        path="/",
    )
    return {"ok": True, "email": admin.email}


@router.post("/logout")
async def admin_logout(response: Response) -> dict:
    # Clears only the admin cookie — any GitHub session in the same browser
    # is intentionally left untouched.
    response.delete_cookie(
        ADMIN_SESSION_COOKIE_NAME,
        httponly=True,
        secure=is_secure_cookie(),
        samesite="none",
        path="/",
    )
    return {"ok": True}


@router.get("/me")
async def admin_me(admin: Admin = Depends(get_current_admin)) -> dict:
    return {
        "id": str(admin.id),
        "email": admin.email,
        "last_login_at": admin.last_login_at.isoformat() if admin.last_login_at else None,
    }
