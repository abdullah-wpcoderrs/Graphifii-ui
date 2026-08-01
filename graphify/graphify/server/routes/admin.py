"""Admin LLM provider credential management.

Phase 4 note: these routes were originally gated on the GitHub session's
`User.role == ADMIN`. They now require an `Admin` principal authenticated by
email/password through the isolated admin cookie (see admin_sessions.py and
routes/admin_auth.py) — a GitHub session, whatever its role, grants no
access here.


Providers mirror graphify/graphify/llm.py's BACKENDS registry entries for
"openai", "claude" (exposed to the UI as "anthropic"), and "gemini" — see
frontend/docs/PHASE3_DISCOVERY.md's review of llm.py. Verification calls
each provider's chat-completions-shaped endpoint directly via httpx rather
than pulling in the optional `openai`/`anthropic` SDK extras, since this is
a single lightweight test call, not corpus processing.

The plaintext API key travels from browser to backend over HTTPS in the
request body (identical to how any other admin settings form handles a
secret) and is encrypted with TOKEN_ENCRYPTION_KEY immediately on arrival —
same scheme as User's GitHub/GitLab/GitBucket tokens (see crypto.py). Only
key_ciphertext/key_iv are persisted; the plaintext never reaches the
database.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from graphify.server.admin_sessions import get_current_admin
from graphify.server.crypto import decrypt, encrypt
from graphify.server.db import get_db
from graphify.server.models import Admin, SystemCredential
from graphify.server.usage import record_usage

logger = logging.getLogger("graphify.server.admin")

router = APIRouter(prefix="/api/admin", tags=["admin"])

_TIMEOUT = 15.0

_PROVIDER_DEFAULTS = {
    "openai": {"base_url": "https://api.openai.com/v1", "default_model": "gpt-4.1-mini"},
    "anthropic": {"base_url": "https://api.anthropic.com", "default_model": "claude-sonnet-4-6"},
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-3-flash-preview",
    },
}


class SaveCredentialRequest(BaseModel):
    provider: str
    api_key: str
    model: str | None = None


class VerifyCredentialRequest(BaseModel):
    provider: str


def _validate_provider(provider: str) -> None:
    if provider not in _PROVIDER_DEFAULTS:
        raise HTTPException(status_code=400, detail=f"unknown provider {provider!r}")


async def _get_credential(provider: str, db: AsyncSession) -> SystemCredential | None:
    result = await db.execute(select(SystemCredential).where(SystemCredential.provider == provider))
    return result.scalar_one_or_none()


async def _call_openai_compat(base_url: str, model: str, api_key: str) -> httpx.Response:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        return await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "user", "content": "Say 'ok'"}], "max_tokens": 5},
        )


async def _call_anthropic(model: str, api_key: str) -> httpx.Response:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        return await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            json={"model": model, "max_tokens": 5, "messages": [{"role": "user", "content": "Say 'ok'"}]},
        )


@router.get("/credentials")
async def list_credentials(
    admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    result = await db.execute(select(SystemCredential))
    configured = {c.provider: c for c in result.scalars().all()}

    return [
        {
            "provider": provider,
            "configured": provider in configured,
            "model": configured[provider].model if provider in configured else None,
            "updated_at": configured[provider].updated_at.isoformat() if provider in configured else None,
        }
        for provider in _PROVIDER_DEFAULTS
    ]


@router.post("/credentials")
async def save_credential(
    payload: SaveCredentialRequest,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _validate_provider(payload.provider)

    existing = await _get_credential(payload.provider, db)
    if existing is None:
        existing = SystemCredential(provider=payload.provider)
        db.add(existing)

    ciphertext, iv = encrypt(payload.api_key)
    existing.key_ciphertext = ciphertext
    existing.key_iv = iv
    existing.model = payload.model

    await db.commit()
    return {"ok": True, "provider": payload.provider}


@router.put("/credentials/{provider}")
async def update_credential(
    provider: str,
    payload: SaveCredentialRequest,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _validate_provider(provider)
    existing = await _get_credential(provider, db)
    if existing is None:
        raise HTTPException(status_code=404, detail="credential not found")

    ciphertext, iv = encrypt(payload.api_key)
    existing.key_ciphertext = ciphertext
    existing.key_iv = iv
    existing.model = payload.model

    await db.commit()
    return {"ok": True}


@router.delete("/credentials/{provider}")
async def delete_credential(
    provider: str, admin: Admin = Depends(get_current_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    _validate_provider(provider)
    existing = await _get_credential(provider, db)
    if existing is not None:
        await db.delete(existing)
        await db.commit()
    return {"ok": True}


@router.post("/credentials/verify")
async def verify_credential(
    payload: VerifyCredentialRequest,
    admin: Admin = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _validate_provider(payload.provider)
    credential = await _get_credential(payload.provider, db)
    if credential is None:
        return {"ok": False, "error": "No API key configured for this provider"}

    api_key = decrypt(credential.key_ciphertext, credential.key_iv)
    defaults = _PROVIDER_DEFAULTS[payload.provider]
    model = credential.model or defaults["default_model"]

    try:
        if payload.provider == "anthropic":
            response = await _call_anthropic(model, api_key)
        else:
            response = await _call_openai_compat(defaults["base_url"], model, api_key)
    except httpx.HTTPError as exc:
        logger.error("credential verify request failed for %s: %s", payload.provider, exc)
        return {"ok": False, "error": "Could not reach the provider API"}

    if response.status_code == 200:
        # Real tokens were just spent proving the key works — record it, same
        # as extraction spend, so the admin spend log isn't blind to it.
        # No user_id/project_id: this is a platform-level check, not tied to
        # any end-user's work.
        usage = response.json().get("usage", {})
        if payload.provider == "anthropic":
            prompt_tokens, completion_tokens = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        else:
            prompt_tokens, completion_tokens = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        await record_usage(
            db,
            provider=payload.provider,
            model=model,
            operation="verify",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return {"ok": True, "model": model}

    return {"ok": False, "error": "API key is invalid or expired"}
