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


def test_images_are_multi_stage_and_do_not_copy_the_repository_root() -> None:
    for name in ("Dockerfile", "Dockerfile.sandbox", "Dockerfile.worker"):
        dockerfile = ROOT.joinpath(name).read_text()
        assert dockerfile.count("FROM ") >= 2
        assert "COPY . " not in dockerfile
        assert "COPY --from=builder" in dockerfile


def test_worker_image_installs_server_extra_and_runs_dedicated_entrypoint() -> None:
    dockerfile = ROOT.joinpath("Dockerfile.worker").read_text()
    assert '".[server]"' in dockerfile
    assert '"graphifyy[server]"' in dockerfile
    assert 'ENTRYPOINT ["graphify-run-worker"]' in dockerfile
