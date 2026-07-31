"""Graphify Cloud IDE backend.

Run locally with:
    cd graphify
    uv run uvicorn graphify.server.app:app --reload --port 8000

Route modules (github, projects, ...) are added in later phases per
BACKEND_IMPLEMENTATION_CHECKLIST.md. This module wires up settings
validation, CORS, the health check, and the Phase 2 auth routes.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from graphify.server.config import get_settings
from graphify.server.routes.auth import router as auth_router

settings = get_settings()

app = FastAPI(title="Graphify Cloud IDE API")

# Credentialed CORS requires an explicit origin — never "*" — per
# docs/github-app-setup.md and frontend/docs/local-development.md.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
