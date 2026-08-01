"""Admin session cookie + password hashing.

Deliberately a separate module from sessions.py rather than extra functions
inside it. The two auth systems share no secret, no cookie, no salt, and no
dependency: `get_current_admin` never falls back to `get_current_user`, and
`get_current_user` knows nothing about admins. Keeping them in separate
files makes an accidental cross-import obvious in review.

Three independent things stop an admin cookie and a GitHub session cookie
from being interchangeable:
  1. different signing secrets   (ADMIN_SESSION_SECRET vs SESSION_SECRET)
  2. different itsdangerous salts (_ADMIN_SESSION_SALT vs _SESSION_SALT)
  3. different cookie names       (graphify_admin_session vs graphify_session)
Any one would suffice; all three are cheap and make the boundary explicit.

Admin sessions are short (12h, vs 30 days for users) because this cookie
guards credential management and user deletion, and admins log in
interactively rather than living in a long-lived browser session.
"""

from __future__ import annotations

import uuid

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.ext.asyncio import AsyncSession

from graphify.server.config import get_settings
from graphify.server.db import get_db
from graphify.server.models import Admin

ADMIN_SESSION_COOKIE_NAME = "graphify_admin_session"

ADMIN_SESSION_MAX_AGE = 60 * 60 * 12  # 12 hours

_ADMIN_SESSION_SALT = "graphify-admin-session"

_hasher = PasswordHasher()


def hash_password(plaintext: str) -> str:
    return _hasher.hash(plaintext)


def verify_password(plaintext: str, password_hash: str) -> bool:
    """Constant-time-ish verify. argon2 raises on mismatch; callers want a bool.

    InvalidHashError is treated as a failed login rather than an error so a
    corrupted or hand-edited row cannot 500 the login endpoint (which would
    also leak, via the status code, that the email exists).
    """
    try:
        _hasher.verify(password_hash, plaintext)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return True


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


def _require_secret() -> str:
    secret = get_settings().admin_session_secret
    if not secret:
        # 503, not 500: the deployment is missing configuration, it is not
        # broken. Mirrors how the GitLab/GitBucket routes report not_configured.
        raise HTTPException(
            status_code=503,
            detail="admin authentication is not configured (ADMIN_SESSION_SECRET unset)",
        )
    return secret


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_require_secret(), salt=_ADMIN_SESSION_SALT)


def create_admin_session_cookie_value(admin_id: uuid.UUID) -> str:
    return _serializer().dumps({"admin_id": str(admin_id)})


def read_admin_session_id(token: str) -> uuid.UUID | None:
    try:
        data = _serializer().loads(token, max_age=ADMIN_SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None

    raw_id = data.get("admin_id")
    if not raw_id:
        return None
    try:
        return uuid.UUID(raw_id)
    except ValueError:
        return None


async def get_current_admin(
    request: Request, db: AsyncSession = Depends(get_db)
) -> Admin:
    token = request.cookies.get(ADMIN_SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")

    admin_id = read_admin_session_id(token)
    if admin_id is None:
        raise HTTPException(status_code=401, detail="admin session expired or invalid")

    admin = await db.get(Admin, admin_id)
    if admin is None:
        raise HTTPException(status_code=401, detail="admin not found")

    # Checked on every request, not just at login, so deactivating an admin
    # revokes their already-issued cookie immediately rather than at expiry.
    if not admin.is_active:
        raise HTTPException(status_code=403, detail="admin account is disabled")

    return admin
