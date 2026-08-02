"""Regression checks for secret-safe container build configuration."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_dockerignore_blocks_secret_and_workspace_artifacts() -> None:
    rules = set(ROOT.joinpath(".dockerignore").read_text().splitlines())
    required = {
        ".env",
        ".env.*",
        "env.backup-*",
        "*.pem",
        "*.key",
        "*credentials*.json",
        "secrets",
        "workspace-storage",
    }
    assert required <= rules


def _instructions(name: str) -> list[str]:
    """Dockerfile lines with comments and blanks removed.

    Matching against raw file text gives false positives: a comment
    *explaining* why `COPY . ` is forbidden trips a naive substring check.
    """
    return [
        line.strip()
        for line in ROOT.joinpath(name).read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_images_are_multi_stage_and_do_not_copy_the_repository_root() -> None:
    for name in ("Dockerfile", "Dockerfile.sandbox", "Dockerfile.worker", "Dockerfile.platform"):
        lines = _instructions(name)
        assert sum(line.startswith("FROM ") for line in lines) >= 2
        assert not any(line.startswith("COPY . ") for line in lines)
        assert any(line.startswith("COPY --from=builder") for line in lines)


def test_worker_image_installs_server_extra_and_runs_dedicated_entrypoint() -> None:
    dockerfile = ROOT.joinpath("Dockerfile.worker").read_text()
    assert '".[server]"' in dockerfile
    assert '"graphifyy[server]"' in dockerfile
    assert 'ENTRYPOINT ["graphify-run-worker"]' in dockerfile


# --------------------------------------------------------------------------
# Unified platform image
# --------------------------------------------------------------------------

PLATFORM = ROOT.joinpath("Dockerfile.platform")


def test_platform_image_installs_the_union_of_every_role_dependency() -> None:
    # A single image only works if it can satisfy all four roles. Splitting
    # the extras per role is what forced separate images in the first place.
    dockerfile = PLATFORM.read_text()
    assert '".[server,openai,anthropic,gemini,sql]"' in dockerfile
    assert '"graphifyy[server,openai,anthropic,gemini,sql]"' in dockerfile


def test_platform_image_dispatches_through_the_role_entrypoint() -> None:
    dockerfile = PLATFORM.read_text()
    assert 'ENTRYPOINT ["python", "/app/platform_entrypoint.py"]' in dockerfile
    # No baked-in default role: an image that starts *something* when
    # misconfigured is how a worker silently becomes a credentialed API.
    assert "ENV SERVICE_ROLE" not in dockerfile


def test_platform_image_carries_what_the_extractor_and_migration_roles_exec() -> None:
    dockerfile = PLATFORM.read_text()
    assert "COPY scripts/sandbox_entrypoint.py /app/sandbox_entrypoint.py" in dockerfile
    # Migrations ship in the same artifact as the code they migrate for, so a
    # deployed digest can never apply a revision its code has not seen.
    assert "COPY alembic.ini /app/alembic.ini" in dockerfile
    assert "COPY alembic /app/alembic" in dockerfile


def test_platform_image_installs_git_and_ca_certificates_for_the_extractor() -> None:
    dockerfile = PLATFORM.read_text()
    assert "git ca-certificates" in dockerfile


def test_platform_image_creates_the_unprivileged_runtime_account() -> None:
    dockerfile = PLATFORM.read_text()
    assert "useradd --create-home --uid 10001 graphify" in dockerfile
    assert "chown -R graphify:graphify" in dockerfile


def test_platform_image_copies_no_secrets_tests_or_local_artifacts() -> None:
    # Every COPY is enumerated here deliberately: adding one should require
    # thinking about whether it can carry a secret into a published layer.
    copies = [
        line.split()[1:]
        for line in PLATFORM.read_text().splitlines()
        if line.startswith("COPY ") and "--from=" not in line
    ]
    sources = {part for parts in copies for part in parts[:-1]}
    allowed = {
        "pyproject.toml",
        "README.md",
        "LICENSE",
        "LICENSE-MIT",
        "NOTICE",
        "graphify",
        "scripts/platform_entrypoint.py",
        "scripts/sandbox_entrypoint.py",
        "alembic.ini",
        "alembic",
    }
    assert sources <= allowed, f"unexpected build inputs: {sources - allowed}"


def test_platform_image_sets_unbuffered_output() -> None:
    assert "ENV PYTHONUNBUFFERED=1" in PLATFORM.read_text()


def test_platform_image_defaults_artifacts_to_the_volume_mount() -> None:
    assert "WORKSPACE_STORAGE_DIR=/data/workspaces" in PLATFORM.read_text()


def test_platform_api_does_not_start_uvicorn_in_reload_mode() -> None:
    app = ROOT.joinpath("graphify/server/app.py").read_text()
    assert "reload=True" not in app
    assert "reload=False" in app


# --------------------------------------------------------------------------
# Extractor parity: Dockerfile.sandbox vs. the platform image's extractor role
# --------------------------------------------------------------------------
#
# Dockerfile.sandbox stays in the tree through the rollback window as the
# behavioural baseline. These tests assert the migrated role did not quietly
# relax any property the original image guaranteed. They compare build
# configuration, not runtime behaviour — the staging extraction in the Phase 2
# exit gate is what proves the rest.


def test_every_subpackage_is_declared_for_packaging() -> None:
    """A subpackage missing from pyproject.toml is invisible until deploy.

    `[tool.setuptools] packages` is an explicit list, so `import`-ing works
    fine from a source checkout while the installed wheel is missing the code
    entirely. That is how graphify.server.routes shipped absent: every test
    passed, and the API only failed once it ran from an image, at import time,
    on startup.
    """
    import tomllib

    declared = set(tomllib.loads(ROOT.joinpath("pyproject.toml").read_text())["tool"]["setuptools"]["packages"])
    on_disk = {
        ".".join(path.parent.relative_to(ROOT).parts)
        for path in ROOT.joinpath("graphify").rglob("__init__.py")
    }

    assert on_disk <= declared, f"not packaged, will be missing from the wheel: {on_disk - declared}"


def test_extractor_role_keeps_the_sandbox_runtime_uid() -> None:
    sandbox_uid = "--uid 10001" in ROOT.joinpath("Dockerfile.sandbox").read_text()
    platform_uid = "--uid 10001" in PLATFORM.read_text()
    assert sandbox_uid and platform_uid


def test_extractor_role_keeps_an_image_owned_ephemeral_workspace() -> None:
    # /workspace is scratch space for one extraction and must never become a
    # mount point or outlive the container.
    for name in ("Dockerfile.sandbox", "Dockerfile.platform"):
        dockerfile = ROOT.joinpath(name).read_text()
        assert "mkdir -p /workspace" in dockerfile
        assert "VOLUME" not in dockerfile


def test_extractor_role_runs_the_same_unmodified_entrypoint_script() -> None:
    # Same file, same path, in both images — the migration changes how the
    # sandbox is *started*, not what it does.
    for name in ("Dockerfile.sandbox", "Dockerfile.platform"):
        assert (
            "COPY scripts/sandbox_entrypoint.py /app/sandbox_entrypoint.py"
            in ROOT.joinpath(name).read_text()
        )


def test_extractor_role_keeps_every_provider_sdk_the_sandbox_had() -> None:
    # The labeling step imports these at runtime; a missing extra would fail
    # mid-extraction rather than at build time.
    platform = PLATFORM.read_text()
    for extra in ("openai", "anthropic", "gemini"):
        assert extra in platform
