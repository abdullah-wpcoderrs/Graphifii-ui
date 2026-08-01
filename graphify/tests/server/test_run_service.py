from __future__ import annotations

from types import SimpleNamespace

from graphify.server.models import ExtractionRunStatus
from graphify.server.run_service import (
    callback_secret_matches,
    hash_callback_secret,
    new_callback_secret,
    transition_allowed,
)


def test_callback_secret_is_random_hashed_and_constant_time_verifiable() -> None:
    secret = new_callback_secret()
    other = new_callback_secret()
    run = SimpleNamespace(callback_secret_hash=hash_callback_secret(secret))

    assert secret != other
    assert len(secret) >= 48
    assert callback_secret_matches(run, secret) is True
    assert callback_secret_matches(run, other) is False
    assert secret not in run.callback_secret_hash


def test_run_state_machine_is_monotonic() -> None:
    assert transition_allowed(ExtractionRunStatus.QUEUED, ExtractionRunStatus.STARTING)
    assert transition_allowed(ExtractionRunStatus.CLONING, ExtractionRunStatus.INDEXING)
    assert transition_allowed(ExtractionRunStatus.INDEXING, ExtractionRunStatus.READY)
    assert not transition_allowed(ExtractionRunStatus.INDEXING, ExtractionRunStatus.CLONING)
    assert not transition_allowed(ExtractionRunStatus.READY, ExtractionRunStatus.INDEXING)
