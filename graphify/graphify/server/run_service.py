"""Shared extraction-run state and callback security helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from graphify.server.models import ExtractionRun, ExtractionRunStatus, Project, ProjectStatus


ACTIVE_RUN_STATUSES = {
    ExtractionRunStatus.STARTING,
    ExtractionRunStatus.CLONING,
    ExtractionRunStatus.INDEXING,
}
OPEN_RUN_STATUSES = {ExtractionRunStatus.QUEUED, *ACTIVE_RUN_STATUSES}
TERMINAL_RUN_STATUSES = {
    ExtractionRunStatus.READY,
    ExtractionRunStatus.FAILED,
    ExtractionRunStatus.CANCELED,
}

ALLOWED_TRANSITIONS = {
    ExtractionRunStatus.QUEUED: {ExtractionRunStatus.STARTING, ExtractionRunStatus.CANCELED},
    ExtractionRunStatus.STARTING: {
        ExtractionRunStatus.CLONING,
        ExtractionRunStatus.FAILED,
        ExtractionRunStatus.CANCELED,
    },
    ExtractionRunStatus.CLONING: {
        ExtractionRunStatus.CLONING,
        ExtractionRunStatus.INDEXING,
        ExtractionRunStatus.FAILED,
        ExtractionRunStatus.CANCELED,
    },
    ExtractionRunStatus.INDEXING: {
        ExtractionRunStatus.INDEXING,
        ExtractionRunStatus.READY,
        ExtractionRunStatus.FAILED,
        ExtractionRunStatus.CANCELED,
    },
}


def new_callback_secret() -> str:
    return secrets.token_urlsafe(48)


def hash_callback_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def callback_secret_matches(run: ExtractionRun, candidate: str) -> bool:
    if not run.callback_secret_hash or not candidate:
        return False
    return hmac.compare_digest(run.callback_secret_hash, hash_callback_secret(candidate))


def transition_allowed(current: ExtractionRunStatus, target: ExtractionRunStatus) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())


def project_status_for_run(status: ExtractionRunStatus) -> ProjectStatus:
    if status in {
        ExtractionRunStatus.QUEUED,
        ExtractionRunStatus.STARTING,
        ExtractionRunStatus.CLONING,
    }:
        return ProjectStatus.CLONING
    if status is ExtractionRunStatus.INDEXING:
        return ProjectStatus.INDEXING
    if status is ExtractionRunStatus.READY:
        return ProjectStatus.READY
    return ProjectStatus.FAILED


def project_from_run(project: Project, run: ExtractionRun) -> None:
    """Update the legacy project progress projection for current UI clients."""
    if project.current_run_id != run.id:
        return
    project.status = project_status_for_run(run.status)
    project.progress_percent = run.progress_percent
    project.status_message = run.status_message
    project.error_message = run.error_message
    project.graph_json_url = run.graph_json_url
    project.sandbox_id = run.deployment_id
    project.started_at = run.started_at
    project.finished_at = run.finished_at


def finish_run(run: ExtractionRun, status: ExtractionRunStatus, error: str | None = None) -> None:
    run.status = status
    run.error_message = error
    run.finished_at = datetime.now(timezone.utc)
    run.active_slot = None
    run.lease_owner = None
    run.lease_expires_at = None
