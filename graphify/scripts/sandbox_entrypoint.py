"""Extraction sandbox entrypoint — runs inside the Railway container.

Lifecycle:
    1. clone REPO_URL into /workspace
    2. `graphify update /workspace`  (extract + cluster; no LLM needed)
    3. `graphify label /workspace`   (LLM community naming; skipped if no key)
    4. build files.json (a UI artifact graphify itself does not emit)
    5. upload graph.json + files.json back to the backend
    6. report READY (or FAILED, with a safe message)

Progress is POSTed to GRAPHIFY_CALLBACK_URL at each phase, authenticated with
GRAPHIFY_CALLBACK_SECRET. The backend persists it; the browser's WebSocket
reads it from there.

Everything is best-effort about *reporting* but strict about *failing*: any
unhandled exception is caught, reported as FAILED with a message safe to show
a user, and exits non-zero so Railway marks the deploy failed too.

Run with no arguments; all configuration is environment variables:

    REPO_URL                  repository to clone            (required)
    PROJECT_ID                for the callback URL           (required)
    GRAPHIFY_CALLBACK_URL     where to POST progress         (required)
    GRAPHIFY_CALLBACK_SECRET  per-run callback secret        (required)
    REPO_TOKEN                git token for private repos    (optional)
    REPO_BRANCH               branch to check out            (optional)
    OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY      (optional)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

WORKSPACE = Path("/workspace")
OUT_DIR = WORKSPACE / "graphify-out"

# Files that bloat the tree without telling a reader anything about the code.
SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".turbo",
    "target",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "graphify-out",
}
MAX_TREE_ENTRIES = 20000


def log(message: str) -> None:
    # Unbuffered: Railway's log view should show progress as it happens, not
    # in one burst when the process exits.
    print(f"[sandbox] {message}", flush=True)


def report(
    status: str, percent: int | None = None, message: str | None = None, error: str | None = None
) -> None:
    """POST progress to the backend. Never raises — losing a progress ping
    must not kill an otherwise healthy extraction."""
    url = os.environ.get("GRAPHIFY_CALLBACK_URL")
    secret = os.environ.get("GRAPHIFY_CALLBACK_SECRET")
    if not url or not secret:
        log(f"no callback configured; would have reported {status} {percent}")
        return

    payload: dict[str, object] = {"status": status}
    if percent is not None:
        payload["progress_percent"] = percent
    if message is not None:
        payload["message"] = message
    if error is not None:
        payload["error"] = error

    event_id = str(uuid.uuid4())
    for attempt in range(3):
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Sandbox-Secret": secret,
                "X-Sandbox-Event-Id": event_id,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response.read()
            return
        except Exception as exc:  # noqa: BLE001 - reporting is best-effort
            if attempt == 2:
                log(f"progress report failed ({status}): {exc}")
            else:
                time.sleep(attempt + 1)


def run(command: list[str], phase: str) -> None:
    """Run a subprocess, streaming its output. Raises RuntimeError on failure."""
    log(f"$ {' '.join(command)}")
    result = subprocess.run(command, cwd=str(WORKSPACE), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout, flush=True)
    if result.stderr:
        print(result.stderr, file=sys.stderr, flush=True)
    if result.returncode != 0:
        # stderr's tail is usually the actionable part; the full output is
        # already in the Railway logs for anyone debugging.
        tail = (result.stderr or result.stdout or "").strip().splitlines()
        detail = tail[-1] if tail else f"exit code {result.returncode}"
        raise RuntimeError(f"{phase} failed: {detail}")


def authenticated_clone_url(repo_url: str, token: str | None) -> str:
    """Inject the token as HTTP basic auth for private clones.

    Kept out of the logged command line — git would otherwise print the token
    in any error message it emits.
    """
    if not token or not repo_url.startswith("https://"):
        return repo_url
    parsed = urllib.parse.urlsplit(repo_url)
    return urllib.parse.urlunsplit(
        (parsed.scheme, f"x-access-token:{token}@{parsed.netloc}", parsed.path, "", "")
    )


def clone() -> None:
    repo_url = os.environ["REPO_URL"]
    token = os.environ.get("REPO_TOKEN")
    branch = os.environ.get("REPO_BRANCH")

    WORKSPACE.mkdir(parents=True, exist_ok=True)

    command = ["git", "clone", "--depth", "1", "--single-branch"]
    if branch:
        command += ["--branch", branch]
    command += [authenticated_clone_url(repo_url, token), str(WORKSPACE)]

    log(f"cloning {repo_url}" + (f" (branch {branch})" if branch else ""))
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        # Scrub the token before this reaches a log or the user's screen.
        stderr = result.stderr or ""
        if token:
            stderr = stderr.replace(token, "***")
        tail = stderr.strip().splitlines()
        raise RuntimeError(f"clone failed: {tail[-1] if tail else 'unknown error'}")


def detect_llm_backend() -> str | None:
    """Map whichever provider key was injected onto llm.py's backend name."""
    for env_var, backend in (
        ("ANTHROPIC_API_KEY", "claude"),
        ("OPENAI_API_KEY", "openai"),
        ("GEMINI_API_KEY", "gemini"),
    ):
        if os.environ.get(env_var):
            return backend
    return None


_TOKEN_COST_RE = re.compile(r"Token cost:\s*([\d,]+)\s*input\s*[·.]\s*([\d,]+)\s*output")


def parse_token_cost(report_path: Path) -> tuple[int, int] | None:
    """Read graphify's own "Token cost: 1,234 input · 567 output" line out of
    GRAPH_REPORT.md, rather than re-deriving token counts ourselves.

    graphify already tracks this internally (label_communities()'s usage_out
    parameter) and writes it into the report; this just surfaces a number
    that already exists instead of duplicating the accounting. Returns None
    if the report is missing or the line isn't found (e.g. labeling never
    ran because no LLM key was present) — that's a normal case, not an error.
    """
    if not report_path.exists():
        return None
    match = _TOKEN_COST_RE.search(report_path.read_text())
    if not match:
        return None
    return int(match.group(1).replace(",", "")), int(match.group(2).replace(",", ""))


def report_usage(backend: str, prompt_tokens: int, completion_tokens: int) -> None:
    """POST token spend to the backend. Best-effort, like report() — a failed
    usage report must not fail an otherwise-successful extraction."""
    url = os.environ.get("GRAPHIFY_CALLBACK_URL", "").replace("/status", "/usage")
    secret = os.environ.get("GRAPHIFY_CALLBACK_SECRET")
    if not url or not secret:
        return

    payload = {
        "provider": backend,
        # No per-run --model flag is passed to `graphify label`, so the exact
        # model graphify chose isn't known here. Cost math is priced per
        # backend, not per model (see server/usage.py), so this is only a
        # display label, not something the cost estimate depends on.
        "model": f"{backend} (sandbox default)",
        "operation": "extraction",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
    event_id = str(uuid.uuid4())
    for attempt in range(3):
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Sandbox-Secret": secret,
                "X-Sandbox-Event-Id": event_id,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                response.read()
            return
        except Exception as exc:  # noqa: BLE001 - reporting is best-effort
            if attempt == 2:
                log(f"usage report failed: {exc}")
            else:
                time.sleep(attempt + 1)


def build_files_json() -> dict:
    """Build the file tree the workspace UI expects.

    graphify does not emit this — it is a Graphify-UI artifact — so it is
    assembled here from the cloned checkout while it still exists.
    """
    entries: list[dict] = []
    truncated = False

    for path in sorted(WORKSPACE.rglob("*")):
        if len(entries) >= MAX_TREE_ENTRIES:
            truncated = True
            break
        relative = path.relative_to(WORKSPACE)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.is_dir():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        entries.append({"path": str(relative), "size": size})

    return {"files": entries, "count": len(entries), "truncated": truncated}


def upload(graph_path: Path, files_path: Path) -> None:
    """Multipart upload of both artifacts, hand-rolled to keep the image
    dependency-free (no requests/httpx needed just for one POST)."""
    url = os.environ["GRAPHIFY_CALLBACK_URL"].replace("/status", "/artifacts")
    secret = os.environ["GRAPHIFY_CALLBACK_SECRET"]

    boundary = "----graphify-sandbox-boundary"
    body = bytearray()
    for field, path in (("graph", graph_path), ("files", files_path)):
        if not path.exists():
            continue
        body += f"--{boundary}\r\n".encode()
        body += (
            f'Content-Disposition: form-data; name="{field}"; filename="{path.name}"\r\n'
            f"Content-Type: application/json\r\n\r\n"
        ).encode()
        body += path.read_bytes()
        body += b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    request = urllib.request.Request(
        url,
        data=bytes(body),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-Sandbox-Secret": secret,
            "X-Sandbox-Event-Id": str(uuid.uuid4()),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        log(f"artifacts uploaded: {response.read().decode()[:200]}")


def main() -> int:
    for required in ("REPO_URL", "PROJECT_ID", "RUN_ID"):
        if not os.environ.get(required):
            log(f"FATAL: {required} is not set")
            return 2
    if bool(os.environ.get("GRAPHIFY_CALLBACK_URL")) != bool(
        os.environ.get("GRAPHIFY_CALLBACK_SECRET")
    ):
        log("FATAL: GRAPHIFY_CALLBACK_URL and GRAPHIFY_CALLBACK_SECRET must be set together")
        return 2

    try:
        report("CLONING", 5, "Cloning repository")
        clone()

        report("INDEXING", 25, "Extracting code structure")
        run([sys.executable, "-m", "graphify", "update", str(WORKSPACE)], "extraction")

        backend = detect_llm_backend()
        if backend:
            report("INDEXING", 70, "Naming communities")
            try:
                run(
                    [
                        sys.executable,
                        "-m",
                        "graphify",
                        "label",
                        str(WORKSPACE),
                        f"--backend={backend}",
                    ],
                    "community labeling",
                )
            except RuntimeError as exc:
                # A graph with placeholder community names is still a useful
                # graph — do not throw away a successful extraction because
                # the LLM step failed.
                log(f"labeling failed, continuing with unlabeled communities: {exc}")

            # Report spend regardless of whether labeling fully succeeded:
            # per-batch tokens are billed by the provider whether or not the
            # reply parsed (see llm.py's label_communities), so a partial
            # failure can still carry real cost that must not go unrecorded.
            cost = parse_token_cost(OUT_DIR / "GRAPH_REPORT.md")
            if cost and (cost[0] or cost[1]):
                report_usage(backend, cost[0], cost[1])
        else:
            log("no LLM key present; skipping community labeling")

        graph_path = OUT_DIR / "graph.json"
        if not graph_path.exists():
            raise RuntimeError("extraction produced no graph.json")

        report("INDEXING", 85, "Preparing workspace files")
        files_path = OUT_DIR / "files.json"
        files_path.write_text(json.dumps(build_files_json()))

        report("INDEXING", 92, "Uploading results")
        upload(graph_path, files_path)

        report("READY", 100, "Workspace ready")
        log("done")
        return 0

    except Exception as exc:  # noqa: BLE001 - top-level guard, reports then exits
        message = str(exc)
        token = os.environ.get("REPO_TOKEN")
        if token:
            message = message.replace(token, "***")
        log(f"FAILED: {message}")
        report("FAILED", error=message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
