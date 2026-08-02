"""Structural checks on the local Compose environment.

compose.yaml is not just developer convenience — it is the only place the
role separation can be exercised end to end before Railway. These tests pin
the properties that make it a faithful rehearsal rather than a different
system that happens to boot:

  * no PostgreSQL container, ever (Neon is the only provider, everywhere)
  * the extractor gets no database credentials
  * one image, built once, shared by every role
  * the worker stays stateless and unpublished

They parse the YAML rather than running Docker, so they are fast and run in
CI without a daemon. Behavioural verification is the Phase 3 exit gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML is only needed for this file")

# compose.yaml sits at the repository root, one level above the graphify/
# package directory that holds this test tree.
COMPOSE = Path(__file__).resolve().parents[3] / "compose.yaml"


@pytest.fixture(scope="module")
def compose() -> dict:
    if not COMPOSE.exists():  # pragma: no cover - only before Phase 3 lands
        pytest.skip(f"{COMPOSE} not present")
    return yaml.safe_load(COMPOSE.read_text())


def test_no_postgres_container_is_ever_defined(compose: dict) -> None:
    """The single most important line in this file.

    Neon is the only PostgreSQL provider in every environment. A local
    Postgres container would mean development runs against a different
    engine, a different migration history, and different pooling behaviour
    than production — the exact class of bug this setup exists to prevent.
    """
    images = [str(service.get("image", "")) for service in compose["services"].values()]
    assert not any("postgres" in image.lower() for image in images)
    assert "postgres" not in compose["services"]
    assert "db" not in compose["services"]


def test_every_role_shares_one_image(compose: dict) -> None:
    services = compose["services"]
    application_roles = ["api", "worker", "migrate", "extractor"]

    images = {services[name]["image"] for name in application_roles}

    # One tag across every role is the whole point of the consolidation: it is
    # what makes "which code is the worker running?" have a single answer.
    assert len(images) == 1


def test_only_the_api_builds_the_image(compose: dict) -> None:
    # Four services declaring the same `build:` would rebuild (and race on)
    # the same tag on every `up`.
    building = [name for name, svc in compose["services"].items() if "build" in svc]
    assert building == ["api"]


def test_each_service_declares_its_role_explicitly(compose: dict) -> None:
    services = compose["services"]
    for name in ("api", "worker", "migrate", "extractor"):
        assert services[name]["environment"]["SERVICE_ROLE"] == name


def test_the_extractor_receives_no_backend_credentials(compose: dict) -> None:
    """The sandbox boundary, enforced in local development too.

    The extractor runs code paths driven by an untrusted repository. It
    reports results through an authenticated callback and needs no database
    connection at all, so it must not be handed the backend env file.
    """
    extractor = compose["services"]["extractor"]

    assert "env_file" not in extractor
    for key in extractor.get("environment", {}):
        assert key not in {"DATABASE_URL", "DATABASE_URL_DIRECT", "SESSION_SECRET"}
        assert not key.startswith("RAILWAY_")


def test_only_the_api_is_stateful_and_published(compose: dict) -> None:
    services = compose["services"]

    # The API alone holds artifacts and a port, mirroring Railway exactly.
    assert "workspace-artifacts:/data/workspaces" in services["api"]["volumes"]
    assert services["api"]["ports"]

    for name in ("worker", "extractor", "migrate"):
        assert "volumes" not in services[name], f"{name} must stay stateless"
        assert "ports" not in services[name], f"{name} must not be published"


def test_batch_roles_are_not_restarted_after_a_successful_exit(compose: dict) -> None:
    # A batch job exiting 0 is success. `unless-stopped` here would re-run
    # every extraction and every migration in a loop — the same Railway
    # restart-policy trap documented in CLAUDE.md.
    for name in ("extractor", "migrate"):
        assert compose["services"][name]["restart"] == "no"


def test_optional_roles_do_not_start_with_a_plain_up(compose: dict) -> None:
    for name in ("extractor", "migrate"):
        assert compose["services"][name]["profiles"]


def test_redis_is_healthchecked_before_dependents_start(compose: dict) -> None:
    services = compose["services"]
    assert services["redis"]["healthcheck"]

    # depends_on without a health condition only waits for the container to
    # exist, not for Redis to accept connections.
    for name in ("api", "worker"):
        assert services[name]["depends_on"]["redis"]["condition"] == "service_healthy"


def test_containers_reach_redis_by_service_name_not_localhost(compose: dict) -> None:
    # Each container has its own loopback; localhost:6379 resolves to nothing.
    for name in ("api", "worker"):
        assert compose["services"][name]["environment"]["REDIS_URL"] == "redis://redis:6379/0"


def test_named_volumes_survive_a_plain_down(compose: dict) -> None:
    # Declared (not anonymous, not bind-mounted) so `down` keeps them and only
    # `down --volumes` erases them.
    assert set(compose["volumes"]) == {"redis-data", "workspace-artifacts"}


def test_the_api_does_not_also_run_the_embedded_worker(compose: dict) -> None:
    # The dedicated worker service is the dispatcher, exactly as in production.
    assert compose["services"]["api"]["environment"]["RUN_WORKER_ENABLED"] == "false"


def test_compose_file_contains_no_secret_values(compose: dict) -> None:
    """Secrets arrive by file reference; this file stays committable."""
    raw = COMPOSE.read_text()
    for marker in ("postgresql://", "postgresql+psycopg://", "-----BEGIN", "sk-", "ghp_"):
        assert marker not in raw
