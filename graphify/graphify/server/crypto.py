"""AES-256-GCM helpers for encrypting GitHub tokens at rest.

Uses TOKEN_ENCRYPTION_KEY (a 32-byte base64 value) directly as the AES key —
no per-record key derivation, since this key never leaves the backend. This
is distinct from the PRD's client-side PBKDF2 flow for admin LLM credentials
(Phase 9), which derives a key from a user-supplied secret in the browser.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from graphify.server.config import get_settings

_NONCE_LENGTH = 12  # bytes, standard for AES-GCM


def _key_bytes() -> bytes:
    key = base64.b64decode(get_settings().token_encryption_key)
    if len(key) != 32:
        raise ValueError("TOKEN_ENCRYPTION_KEY must decode to exactly 32 bytes")
    return key


def encrypt(plaintext: str) -> tuple[str, str]:
    """Returns (ciphertext_b64, iv_b64)."""
    nonce = os.urandom(_NONCE_LENGTH)
    ciphertext = AESGCM(_key_bytes()).encrypt(nonce, plaintext.encode("utf-8"), None)
    return (
        base64.b64encode(ciphertext).decode("ascii"),
        base64.b64encode(nonce).decode("ascii"),
    )


def decrypt(ciphertext_b64: str, iv_b64: str) -> str:
    nonce = base64.b64decode(iv_b64)
    ciphertext = base64.b64decode(ciphertext_b64)
    plaintext = AESGCM(_key_bytes()).decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")
