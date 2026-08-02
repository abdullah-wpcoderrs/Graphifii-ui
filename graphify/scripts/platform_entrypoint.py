"""Role dispatcher for the unified `graphify-platform` image.

One image, four start-up modes. Railway (and local Compose) decide which one
by setting SERVICE_ROLE; nothing else about the container differs:

    SERVICE_ROLE=api        -> graphify-server              (public backend)
    SERVICE_ROLE=worker     -> graphify-run-worker          (private queue worker)
    SERVICE_ROLE=extractor  -> python /app/sandbox_entrypoint.py
    SERVICE_ROLE=migrate    -> alembic upgrade head         (one-shot job)

Why a dispatcher instead of four ENTRYPOINTs / four images: a single immutable
digest can then be promoted through staging to production and pointed at by
every service, so "which code is the worker running?" has exactly one answer.

Two properties this file exists to guarantee, both covered by
tests/server/test_platform_entrypoint.py:

1. **Process replacement, not a subprocess.** `os.execvpe` overwrites this
   process, so PID 1 in the container *is* the real API/worker/extractor.
   If we spawned a child instead, Railway's SIGTERM on redeploy or cancel
   would land on this wrapper and the real process would either never see it
   or get killed ungracefully mid-write.

2. **Fail closed.** An unset, empty, or misspelled role must never silently
   fall through to a default. `SERVICE_ROLE=woker` starting the API would be
   a security event, not a typo: the API is the role that holds database
   credentials and a public domain. Unknown roles exit non-zero with a
   message naming the valid ones and nothing else.

Nothing here logs the environment, and no role echoes a variable value —
these processes run where Railway captures stdout into a durable log.

**Why PID 1 starts as root and the real process does not.** Railway attaches
persistent volumes root-owned, so a container that is already unprivileged at
start cannot create or take ownership of its own mount point. This dispatcher
therefore runs as root just long enough to prepare the API's artifact
directory, then permanently drops to uid 10001 *before* exec'ing anything.
Every role — including the extractor, which executes code paths driven by an
untrusted repository — ends up running unprivileged. The drop is verified, not
assumed: if it cannot be completed the container exits rather than continuing
as root.
"""

from __future__ import annotations

import os
import pwd
import sys
from collections.abc import Mapping

# Where Dockerfile.platform lands the sandbox entrypoint. Overridable so the
# tests (and a developer running this from a checkout) can exercise dispatch
# without /app existing.
SANDBOX_ENTRYPOINT = os.environ.get("GRAPHIFY_SANDBOX_ENTRYPOINT", "/app/sandbox_entrypoint.py")

# The unprivileged account Dockerfile.platform creates. Overridable only for
# tests; production should never change these.
RUNTIME_USER = os.environ.get("GRAPHIFY_RUNTIME_USER", "graphify")

ROLE_API = "api"
ROLE_WORKER = "worker"
ROLE_EXTRACTOR = "extractor"
ROLE_MIGRATE = "migrate"

VALID_ROLES = (ROLE_API, ROLE_WORKER, ROLE_EXTRACTOR, ROLE_MIGRATE)

# A migration needs the database and ordinary process plumbing, not the API's
# OAuth, session, Railway, LLM, or encryption credentials. Building its child
# environment from an allowlist prevents a newly added backend secret from
# silently reaching Alembic through Compose's shared local env file.
MIGRATION_ENV_PASSTHROUGH = {
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "PYTHONHOME",
    "PYTHONPATH",
    "PYTHONUNBUFFERED",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TZ",
}


class RoleError(Exception):
    """SERVICE_ROLE is missing, unknown, or its required inputs are absent."""


def resolve_command(role: str) -> list[str]:
    """Map a role to the argv that replaces this process.

    The API and worker go through console scripts declared in pyproject.toml
    ([project.scripts]) rather than `python -m`, so a packaging mistake that
    drops an entrypoint fails at container start rather than at first request.
    """
    if role == ROLE_API:
        return ["graphify-server"]
    if role == ROLE_WORKER:
        return ["graphify-run-worker"]
    if role == ROLE_EXTRACTOR:
        # sys.executable, not a bare "python": guarantees the interpreter that
        # owns the installed graphify package, whatever the image's PATH says.
        return [sys.executable, SANDBOX_ENTRYPOINT]
    if role == ROLE_MIGRATE:
        return ["alembic", "upgrade", "head"]
    raise RoleError(
        f"unknown SERVICE_ROLE {role!r} — expected one of: {', '.join(VALID_ROLES)}"
    )


def build_environment(role: str, env: Mapping[str, str]) -> dict[str, str]:
    """Return the environment for the replacement process.

    Neon publishes two connection strings: a *pooled* one (PgBouncer, correct
    for application traffic) and a *direct* one. API/worker/extractor child
    environments have the direct credential removed. The migration child is
    built from a small process-plumbing allowlist and receives the direct URL
    as DATABASE_URL; it never inherits the API's application secrets.

    Compose still reads one raw local .env file, so the root dispatcher sees
    that file briefly. The exec boundary is where least privilege is enforced:
    after process replacement, only the variables required by the selected
    workload remain.
    """
    if role != ROLE_MIGRATE:
        result = dict(env)
        # The direct Neon credential is administrative. Compose reads one raw
        # .env file for local convenience, but the long-running application
        # processes must retain only the pooled URL they actually use.
        result.pop("DATABASE_URL_DIRECT", None)
        return result

    direct = (env.get("DATABASE_URL_DIRECT") or "").strip()
    if not direct:
        raise RoleError(
            "SERVICE_ROLE=migrate requires DATABASE_URL_DIRECT (Neon's direct, "
            "non-pooled connection string). Alembic must not run through the "
            "pooled endpoint."
        )
    result = {key: value for key, value in env.items() if key in MIGRATION_ENV_PASSTHROUGH}
    result["SERVICE_ROLE"] = ROLE_MIGRATE
    result["DATABASE_URL"] = direct
    return result


def apply_runtime_identity(environment: Mapping[str, str]) -> dict[str, str]:
    """Make process identity variables agree with the uid/gid we drop to.

    The image starts as root, so Docker initially supplies HOME=/root. Merely
    calling setuid does not update the environment. Leaving HOME behind breaks
    libpq/psycopg: it probes /root/.postgresql for client certificates and the
    unprivileged process receives PermissionError before connecting to Neon.
    """
    entry = pwd.getpwnam(RUNTIME_USER)
    result = dict(environment)
    result["HOME"] = entry.pw_dir
    result["USER"] = entry.pw_name
    result["LOGNAME"] = entry.pw_name
    return result


def prepare_volume(role: str, env: Mapping[str, str]) -> None:
    """Make the API's artifact mount usable by the unprivileged runtime user.

    Only the API role has a persistent volume. The worker is stateless and the
    extractor gets an ephemeral /workspace that Dockerfile.platform already
    owns correctly, so neither needs anything here.

    No-op when we are not root — locally the directory is usually already
    owned correctly, and a non-root process failing to chown is not a reason
    to refuse to start. If the directory really is unwritable, the API's own
    storage layer raises with a clearer, more specific error than we could.
    """
    if role != ROLE_API or os.geteuid() != 0:
        return

    directory = (env.get("WORKSPACE_STORAGE_DIR") or "").strip()
    if not directory:
        return

    try:
        uid, gid = _runtime_ids()
        os.makedirs(directory, exist_ok=True)
        os.chown(directory, uid, gid)
    except OSError as exc:
        # Fail loudly but do not exit: a read-only or externally managed mount
        # is a deployment decision, and the API will report the real problem.
        print(f"[platform] could not prepare {directory}: {exc}", file=sys.stderr)


def _runtime_ids() -> tuple[int, int]:
    entry = pwd.getpwnam(RUNTIME_USER)
    return entry.pw_uid, entry.pw_gid


def drop_privileges() -> None:
    """Permanently become the unprivileged runtime user.

    setgroups() first, then setgid, then setuid — that order matters: after
    setuid the process no longer has the privilege to shed its supplementary
    groups or its gid, so doing them in the other order silently leaves root
    group membership behind.

    The post-conditions are asserted rather than trusted. A container that
    believes it dropped privileges but did not is worse than one that never
    tried, because every later security argument rests on this line.
    """
    if os.geteuid() != 0:
        return

    uid, gid = _runtime_ids()
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)

    if os.geteuid() != uid or os.getegid() != gid or os.getuid() != uid:
        raise RoleError("failed to drop root privileges — refusing to start")
    try:
        os.setuid(0)
    except OSError:
        pass  # expected: the drop is irreversible
    else:
        raise RoleError("root privileges were restorable after the drop — refusing to start")


def main(argv: list[str] | None = None) -> int:
    role = (os.environ.get("SERVICE_ROLE") or "").strip().lower()
    if not role:
        print(
            "SERVICE_ROLE is not set. This image starts nothing by default; set "
            f"SERVICE_ROLE to one of: {', '.join(VALID_ROLES)}",
            file=sys.stderr,
        )
        return 2

    try:
        command = resolve_command(role)
        environment = apply_runtime_identity(build_environment(role, os.environ))
        # Order is deliberate: prepare the mount while still root, then shed
        # root, then exec. Nothing privileged happens after this point.
        prepare_volume(role, os.environ)
        drop_privileges()
    except RoleError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # Any extra argv is forwarded, so `docker run image --help` style
    # pass-through still works for debugging a role locally.
    extra = list(argv if argv is not None else sys.argv[1:])
    command.extend(extra)

    print(f"[platform] starting role={role} command={command[0]}", flush=True)

    try:
        os.execvpe(command[0], command, environment)
    except OSError as exc:  # pragma: no cover - depends on image contents
        print(f"failed to start role {role!r}: {exc}", file=sys.stderr)
        return 127
    return 0  # pragma: no cover - unreachable after a successful exec


if __name__ == "__main__":
    raise SystemExit(main())
