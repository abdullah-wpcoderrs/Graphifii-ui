"""Graphify Cloud IDE backend.

Run locally with:
    cd graphify
    uv run graphify-server
    # equivalent to: uv run uvicorn graphify.server.app:app --reload --port 8000

This module wires up settings validation, CORS, the health check, and all
route modules (auth from Phase 2; projects/github/integrations/admin from
Phase 3; isolated admin email/password auth from Phase 4).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from graphify.server.config import get_settings
from graphify.server.routes.admin import router as admin_router
from graphify.server.routes.admin_auth import router as admin_auth_router
from graphify.server.routes.admin_data import router as admin_data_router
from graphify.server.routes.auth import router as auth_router
from graphify.server.routes.github import router as github_router
from graphify.server.routes.integrations import router as integrations_router
from graphify.server.routes.launch import router as launch_router
from graphify.server.routes.projects import router as projects_router
from graphify.server.routes.usage import router as usage_router

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
app.include_router(projects_router)
app.include_router(launch_router)
app.include_router(usage_router)
app.include_router(github_router)
app.include_router(integrations_router)
# admin_auth_router must be included before admin_router: both mount under
# /api/admin, and the login/logout/me paths are unauthenticated by design
# while everything in admin_router requires an admin session.
app.include_router(admin_auth_router)
app.include_router(admin_router)
app.include_router(admin_data_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def run() -> None:
    """Entry point for `uv run graphify-server` (see [project.scripts])."""
    import uvicorn

    uvicorn.run("graphify.server.app:app", host="0.0.0.0", port=8000, reload=True)
