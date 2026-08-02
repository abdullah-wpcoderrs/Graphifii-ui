"""Graphify Cloud IDE backend.

Run locally with:
    cd graphify
    uv run graphify-server
    # For source auto-reload instead:
    # uv run uvicorn graphify.server.app:app --reload --port 8000

This module wires up settings validation, CORS, the health check, and all
route modules (auth from Phase 2; projects/github/integrations/admin from
Phase 3; isolated admin email/password auth from Phase 4).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from graphify.server.config import get_settings
from graphify.server.routes.agent import router as agent_router
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
logger = logging.getLogger("graphify.server.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from graphify.server.redis_queue import build_redis_run_queue
    from graphify.server.readiness import wait_for_database

    # A suspended Neon branch may need several seconds to wake. Do not expose
    # the API until a real SQL round trip succeeds; if the bounded retries are
    # exhausted, startup fails and the container restart policy tries again.
    await wait_for_database()

    run_queue = build_redis_run_queue(settings)
    if run_queue is not None:
        try:
            await run_queue.start()
        except Exception:  # noqa: BLE001 - PostgreSQL polling is the fallback
            logger.exception("Redis run queue unavailable; using PostgreSQL polling fallback")
            await run_queue.close()
            run_queue = None
    app.state.run_queue = run_queue

    worker_task = None
    if settings.run_worker_enabled:
        from graphify.server.run_worker import run_queue_worker

        worker_task = asyncio.create_task(
            run_queue_worker(run_queue), name="extraction-run-worker"
        )
    try:
        yield
    finally:
        if worker_task is not None:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
        if run_queue is not None:
            await run_queue.close()


app = FastAPI(title="Graphify Cloud IDE API", lifespan=lifespan)

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
app.include_router(agent_router)
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
    from graphify.server.readiness import database_is_ready

    if not await database_is_ready():
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok"}


def run() -> None:
    """Entry point for `uv run graphify-server` (see [project.scripts])."""
    import uvicorn

    # Production uses a single process so the platform entrypoint's exec means
    # PID 1 is the actual uvicorn server. For source-development auto-reload,
    # run `uv run uvicorn graphify.server.app:app --reload --port 8000`.
    uvicorn.run("graphify.server.app:app", host="0.0.0.0", port=8000, reload=False)
