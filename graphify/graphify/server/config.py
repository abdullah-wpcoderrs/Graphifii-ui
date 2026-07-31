"""Environment configuration for the Graphify backend.

Validates on first access so the server fails fast with a clear error
instead of surfacing a confusing failure deep in a request handler.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# graphify/server/config.py -> graphify/server -> graphify (package) -> graphify (repo root)
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    frontend_url: str
    backend_url: str

    database_url: str

    session_secret: str
    token_encryption_key: str

    github_app_id: str
    github_client_id: str
    github_client_secret: str
    github_private_key: str
    github_webhook_secret: str

    @field_validator(
        "database_url",
        "session_secret",
        "token_encryption_key",
        "github_app_id",
        "github_client_id",
        "github_client_secret",
        "github_private_key",
        "github_webhook_secret",
    )
    @classmethod
    def _reject_placeholders(cls, value: str, info) -> str:
        if not value or value.upper().startswith("REPLACE_WITH") or "replace-with" in value.lower():
            raise ValueError(
                f"{info.field_name} is unset or still a placeholder — "
                f"fill in graphify/.env (see docs/github-app-setup.md)"
            )
        return value

    @field_validator("github_private_key")
    @classmethod
    def _validate_pem_shape(cls, value: str) -> str:
        # Catches the failure mode where a multi-line PEM was pasted into
        # .env unquoted: dotenv then only captures the first line ("-----
        # BEGIN ... KEY-----" with no body), which otherwise passes the
        # placeholder check above silently and fails much later, inside
        # GitHub App JWT signing, with a confusing cryptography error.
        # Use scripts/set_github_private_key.py to set this value correctly.
        if "BEGIN" not in value or "END" not in value or "\n" not in value:
            raise ValueError(
                "GITHUB_PRIVATE_KEY doesn't look like a complete PEM (missing "
                "BEGIN/END markers or real newlines) — this usually means it "
                "was pasted unquoted and got truncated to one line by dotenv. "
                "Run: python3 scripts/set_github_private_key.py /path/to/key.pem"
            )
        return value

    @model_validator(mode="after")
    def _secrets_must_differ(self) -> "Settings":
        if self.session_secret == self.token_encryption_key:
            raise ValueError("SESSION_SECRET and TOKEN_ENCRYPTION_KEY must be different values")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
