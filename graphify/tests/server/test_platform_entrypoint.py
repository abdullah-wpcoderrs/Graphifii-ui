"""Role dispatch and fail-closed tests for the unified platform image.

These are pure unit tests: no database, no Docker, no network. The dispatcher
is the one piece of the consolidation that decides *what runs*, so its
behaviour is pinned here rather than discovered in production.

The load-by-path dance below exists because scripts/ is not an importable
package — the file has to be readable both as the container's PID 1 and as a
module under test, and copying it into graphify/ just to import it would put
container plumbing in the published wheel.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _load_entrypoint():
    spec = importlib.util.spec_from_file_location(
        "graphify_platform_entrypoint", ROOT / "scripts" / "platform_entrypoint.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


entrypoint = _load_entrypoint()


# --------------------------------------------------------------------------
# Role -> command mapping
# --------------------------------------------------------------------------


def test_api_role_starts_the_server_console_script() -> None:
    assert entrypoint.resolve_command("api") == ["graphify-server"]


def test_worker_role_starts_the_dedicated_run_worker() -> None:
    assert entrypoint.resolve_command("worker") == ["graphify-run-worker"]


def test_extractor_role_runs_the_existing_sandbox_entrypoint() -> None:
    command = entrypoint.resolve_command("extractor")
    # sys.executable rather than a bare "python": the interpreter that owns
    # the installed graphify package, regardless of PATH.
    assert command[0] == sys.executable
    assert command[1].endswith("sandbox_entrypoint.py")


def test_migrate_role_runs_alembic_upgrade_head() -> None:
    assert entrypoint.resolve_command("migrate") == ["alembic", "upgrade", "head"]


def test_every_documented_role_resolves() -> None:
    # Guards against VALID_ROLES and resolve_command drifting apart — the
    # error message would otherwise advertise a role that cannot start.
    for role in entrypoint.VALID_ROLES:
        assert entrypoint.resolve_command(role)


# --------------------------------------------------------------------------
# Fail closed
# --------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["", "woker", "API ", "sandbox", "shell", "root"])
def test_unknown_roles_are_rejected(role: str) -> None:
    with pytest.raises(entrypoint.RoleError):
        entrypoint.resolve_command(role)


def test_missing_role_exits_non_zero_without_starting_anything(monkeypatch, capsys) -> None:
    monkeypatch.delenv("SERVICE_ROLE", raising=False)
    monkeypatch.setattr(entrypoint.os, "execvpe", _forbidden_exec)

    assert entrypoint.main([]) == 2
    assert "SERVICE_ROLE" in capsys.readouterr().err


def test_unknown_role_exits_non_zero_without_starting_anything(monkeypatch, capsys) -> None:
    monkeypatch.setenv("SERVICE_ROLE", "worker-2")
    monkeypatch.setattr(entrypoint.os, "execvpe", _forbidden_exec)

    assert entrypoint.main([]) == 2
    stderr = capsys.readouterr().err
    assert "unknown SERVICE_ROLE" in stderr
    # The message must name the alternatives; a bare rejection sends the
    # operator to the source to find out what is valid.
    assert "extractor" in stderr


def _forbidden_exec(*_args, **_kwargs):
    raise AssertionError("a rejected role must never exec a process")


# --------------------------------------------------------------------------
# Migration role and the pooled/direct Neon split
# --------------------------------------------------------------------------


def test_migrate_promotes_the_direct_url_for_alembic() -> None:
    env = {
        "PATH": "/usr/local/bin:/usr/bin",
        "DATABASE_URL": "postgresql://pooled",
        "DATABASE_URL_DIRECT": "postgresql://direct",
        "SESSION_SECRET": "must-not-reach-alembic",
        "RAILWAY_API_TOKEN": "must-not-reach-alembic",
    }

    result = entrypoint.build_environment("migrate", env)

    # Alembic reads DATABASE_URL; the direct, non-pooled endpoint is what it
    # must land on. See alembic/env.py.
    assert result["DATABASE_URL"] == "postgresql://direct"
    assert result == {
        "PATH": "/usr/local/bin:/usr/bin",
        "SERVICE_ROLE": "migrate",
        "DATABASE_URL": "postgresql://direct",
    }


def test_migrate_without_a_direct_url_fails_rather_than_using_the_pooled_one() -> None:
    with pytest.raises(entrypoint.RoleError, match="DATABASE_URL_DIRECT"):
        entrypoint.build_environment("migrate", {"DATABASE_URL": "postgresql://pooled"})


def test_migrate_treats_a_blank_direct_url_as_missing() -> None:
    with pytest.raises(entrypoint.RoleError, match="DATABASE_URL_DIRECT"):
        entrypoint.build_environment("migrate", {"DATABASE_URL_DIRECT": "   "})


def test_runtime_identity_environment_matches_the_dropped_user(monkeypatch) -> None:
    monkeypatch.setattr(
        entrypoint.pwd,
        "getpwnam",
        lambda _name: SimpleNamespace(
            pw_name="graphify",
            pw_dir="/home/graphify",
            pw_uid=10001,
            pw_gid=10001,
        ),
    )

    result = entrypoint.apply_runtime_identity(
        {"HOME": "/root", "USER": "root", "LOGNAME": "root", "DATABASE_URL": "db"}
    )

    assert result == {
        "HOME": "/home/graphify",
        "USER": "graphify",
        "LOGNAME": "graphify",
        "DATABASE_URL": "db",
    }


@pytest.mark.parametrize("role", ["api", "worker", "extractor"])
def test_non_migration_roles_never_see_the_direct_url_promoted(role: str) -> None:
    env = {"DATABASE_URL": "postgresql://pooled", "DATABASE_URL_DIRECT": "postgresql://direct"}

    result = entrypoint.build_environment(role, env)

    # The application must stay on the pooled endpoint: the direct one has a
    # hard connection cap that long-running API/worker processes exhaust.
    assert result["DATABASE_URL"] == "postgresql://pooled"
    assert "DATABASE_URL_DIRECT" not in result


# --------------------------------------------------------------------------
# Process replacement and privilege handling
# --------------------------------------------------------------------------


def test_dispatch_replaces_the_process_rather_than_spawning_a_child(monkeypatch) -> None:
    captured = {}

    def fake_exec(path, argv, env):
        captured["path"] = path
        captured["argv"] = argv
        captured["env"] = env
        raise SystemExit(0)

    monkeypatch.setenv("SERVICE_ROLE", "worker")
    monkeypatch.setattr(entrypoint.os, "execvpe", fake_exec)
    monkeypatch.setattr(entrypoint, "apply_runtime_identity", dict)
    monkeypatch.setattr(entrypoint, "drop_privileges", lambda: None)

    with pytest.raises(SystemExit):
        entrypoint.main([])

    # execvpe, not subprocess: PID 1 must *become* the worker so Railway's
    # SIGTERM on redeploy or cancel reaches the real process.
    assert captured["path"] == "graphify-run-worker"
    assert captured["argv"] == ["graphify-run-worker"]


def test_role_is_case_and_whitespace_tolerant(monkeypatch) -> None:
    # A trailing space in a dashboard field should not take the API down.
    captured = {}

    def fake_exec(path, argv, env):
        captured["path"] = path
        raise SystemExit(0)

    monkeypatch.setenv("SERVICE_ROLE", "  API  ")
    monkeypatch.setattr(entrypoint.os, "execvpe", fake_exec)
    monkeypatch.setattr(entrypoint, "apply_runtime_identity", dict)
    monkeypatch.setattr(entrypoint, "drop_privileges", lambda: None)

    with pytest.raises(SystemExit):
        entrypoint.main([])

    assert captured["path"] == "graphify-server"


def test_privilege_drop_is_a_no_op_when_already_unprivileged(monkeypatch) -> None:
    # The test process is not root; the drop must not raise or try to setuid.
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: 1000)
    called = []
    monkeypatch.setattr(entrypoint.os, "setuid", lambda uid: called.append(uid))

    entrypoint.drop_privileges()

    assert called == []


def test_volume_preparation_only_applies_to_the_api_role(monkeypatch) -> None:
    # The worker is stateless and the extractor's /workspace is ephemeral and
    # already owned correctly by the image — neither may touch a mount.
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        entrypoint.os,
        "makedirs",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not create directories")),
    )

    entrypoint.prepare_volume("worker", {"WORKSPACE_STORAGE_DIR": "/data/workspaces"})
    entrypoint.prepare_volume("extractor", {"WORKSPACE_STORAGE_DIR": "/data/workspaces"})


def test_api_volume_preparation_chowns_to_the_runtime_user(monkeypatch, tmp_path) -> None:
    made: list[str] = []
    owned: list[tuple] = []

    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: 0)
    monkeypatch.setattr(entrypoint, "_runtime_ids", lambda: (10001, 10001))
    monkeypatch.setattr(entrypoint.os, "makedirs", lambda p, exist_ok=False: made.append(p))
    monkeypatch.setattr(entrypoint.os, "chown", lambda p, u, g: owned.append((p, u, g)))

    entrypoint.prepare_volume("api", {"WORKSPACE_STORAGE_DIR": str(tmp_path / "workspaces")})

    assert made and owned == [(str(tmp_path / "workspaces"), 10001, 10001)]


def test_api_volume_preparation_survives_an_unwritable_mount(monkeypatch, capsys) -> None:
    # A read-only or externally managed mount is a deployment decision. The
    # API reports the real problem far more precisely than we can here, so
    # failing to chown must not stop the container from starting.
    monkeypatch.setattr(entrypoint.os, "geteuid", lambda: 0)
    monkeypatch.setattr(entrypoint, "_runtime_ids", lambda: (10001, 10001))
    monkeypatch.setattr(
        entrypoint.os,
        "makedirs",
        lambda *a, **k: (_ for _ in ()).throw(PermissionError("read-only")),
    )

    entrypoint.prepare_volume("api", {"WORKSPACE_STORAGE_DIR": "/data/workspaces"})

    assert "could not prepare" in capsys.readouterr().err


def test_no_role_prints_the_environment(monkeypatch, capsys) -> None:
    def fake_exec(path, argv, env):
        raise SystemExit(0)

    monkeypatch.setenv("SERVICE_ROLE", "api")
    monkeypatch.setenv("SESSION_SECRET", "super-secret-value")
    monkeypatch.setattr(entrypoint, "apply_runtime_identity", dict)
    monkeypatch.setattr(entrypoint, "drop_privileges", lambda: None)
    monkeypatch.setattr(entrypoint.os, "execvpe", fake_exec)

    with pytest.raises(SystemExit):
        entrypoint.main([])

    output = capsys.readouterr()
    # The startup line names the role and the command, never a value.
    assert "super-secret-value" not in output.out + output.err
