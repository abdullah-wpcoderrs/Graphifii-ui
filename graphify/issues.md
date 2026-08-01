# Security Audit Report

## Executive Summary

Do not deploy the reviewed backend until the High findings are fixed. The most serious risks are production secrets being copied into the main Docker image, shared mutable Railway deployment configuration that is unsafe under concurrent launches, and a non-atomic AI budget check that an authenticated user can bypass with parallel WebSocket connections. The audit covered the FastAPI backend, database models/migrations, sandbox entrypoint, deployment files, and relevant backend tests; it did not change application code.

## Detected Stack and Scope

- **Framework**: FastAPI, Uvicorn, Pydantic settings, HTTP and WebSocket routes.
- **Database**: PostgreSQL via async SQLAlchemy and psycopg; Alembic migrations.
- **Authentication**: GitHub OAuth user sessions; separate Argon2-backed admin sessions; signed `itsdangerous` cookies.
- **Deployment**: Docker, a separate extraction-sandbox image, and Railway GraphQL deployment orchestration.
- **Other**: GitHub/GitLab/GitBucket integrations, AES-GCM token encryption, OpenAI-compatible/Anthropic LLM streaming, local artifact storage.
- **Review scope**: `graphify/server`, `scripts/sandbox_entrypoint.py`, `Dockerfile*`, `.dockerignore`, `.gitignore`, `pyproject.toml`, `uv.lock`, Alembic migrations, and `tests/server`.
- **Special focus**: parallel execution, race conditions, duplicate side effects, idempotency, unbounded resource use, and production-only behavioral failures.
- **Limitations / not verified**: Railway runtime semantics and deployment history, cloud WAF/rate limits, provider hard-spend caps, production database policies/backups, secret rotation history, and whether a vulnerable Docker image has already been built or pushed.
- **Audit date**: 2026-08-01.
- **Tools**: manual data/control-flow review; Ruff; Bandit 1.9.4; pip-audit 2.10.0. The dependency audit examined the active local environment because pip-audit did not accept `uv.lock` as a lockfile.

## Results

- **Project Score**: 32/100 — Poor — significant risk (prioritization aid, not a standardized risk metric).
- **Checklist status**: 9 passed, 13 finding, 3 not applicable, 5 not verified.
- **Unique issues**: 10.
- **Deployment recommendation**: Block production deployment until Findings 1-3 are fixed and verified with concurrency tests.

## Quick Wins

| # | Issue | Severity | Estimated effort | Fix |
|---|---|---:|---:|---|
| 1 | Docker build includes local secret files | 9/10 High | <1 hour plus rotation | Exclude `.env`, `env.backup-*`, keys, and credentials in `.dockerignore`; rotate if any image was built or shared. |
| 4 | AI budget check is raceable | 8/10 High | 1-2 days | Reserve estimated spend atomically before provider calls and cap concurrent turns per user. |
| 7 | Admin limiter is per-process and unbounded | 6/10 Medium | 1 day | Use a bounded shared Redis/database limiter keyed separately by account and origin. |
| 9 | Debug-style reload and missing headers | 4/10 Low | <1 hour | Make reload opt-in and add production security-header middleware. |

## Findings

### 1. [9/10 High] Main Docker build copies live production credentials into the image

- **Location**: `Dockerfile:10-16`; `.dockerignore:1-25`; `.env:12-61`; `env.backup-1785543035:12-61`; `.gitignore:4-6`.
- **Evidence**: The main image uses `COPY . /app`, while `.dockerignore` does not exclude `.env`, `env.backup-*`, private keys, or credential files. Redacted local inspection confirmed non-placeholder values for the database URL, session/encryption secrets, OAuth secrets, a private key, Railway credentials, the sandbox callback secret, and the admin password. The timestamped backup is also not matched by the repository's `.env.*` ignore rule. No values are reproduced here.
- **Attack scenario**: A normal `docker build` sends both secret-bearing files in the build context and copies them into an image layer. Anyone able to pull, inspect, export, or access the image/build cache can recover credentials even if a later layer deletes the files.
- **Impact**: Database access, session forgery, token decryption, OAuth compromise, Railway control, sandbox callback forgery, and admin takeover, depending on which credentials remain valid.
- **Confidence**: High. Inclusion follows directly from Docker build rules; whether an affected image was already built or distributed is not verified.
- **Remediation**: Add `.env`, `.env.*`, `env.backup-*`, `*.pem`, `*.key`, `secrets/`, credential JSON, local databases, logs, and workspace artifacts to `.dockerignore`. Move backups outside the repository. Use Docker secret mounts or deployment environment variables. If this Dockerfile has ever been built with the current context, inspect image/build-cache exposure and rotate every affected credential, prioritizing database, session/admin signing, token encryption, GitHub private/client secrets, Railway token, and callback secret.
- **Verification**: Use a synthetic canary secret in an ignored test file, build the image, and confirm neither the file nor canary exists in the final filesystem or saved image layers. Run a secret scanner against the build context and image tar without printing values.

### 2. [9/10 High] Shared Railway service configuration is not isolated per launch

- **Location**: `graphify/server/sandbox.py:86-160`; `graphify/server/routes/launch.py:134-224`.
- **Evidence**: Every request first replaces one shared Railway service/environment variable collection (`replace=True`) and then triggers that service in a separate GraphQL call. There is no transaction, per-run service, queue, distributed lock, or immutable deployment input connecting those operations. The variables include project ID, repository URL/token, callback secret, and the active platform LLM key.
- **Attack scenario**: Launch A writes variables, launch B overwrites them, and then A triggers the service. The resulting deployment can use B's project/repository identity. Repeated or concurrent launches also contend on the same service and “latest deployment” lookup, so a project can record another launch's deployment ID.
- **Impact**: Cross-project artifact/status corruption, incorrect credential/repository pairing, spend misattribution, lost or replaced work, and non-deterministic production behavior under ordinary multi-user load.
- **Confidence**: High for the application race; exact Railway snapshot/cancellation behavior is not verified and may increase the impact.
- **Remediation**: Provision an immutable per-run job/deployment with a unique `run_id`, or serialize launches through a durable queue and distributed lock if Railway only supports mutable service variables. Never use a “latest deployment” query to identify a specific launch; capture a returned deployment/job ID or correlate a unique run label. Store and verify `(project_id, run_id, deployment_id)` at every callback.
- **Verification**: A barrier-controlled concurrency test must interleave two launches at every external-call boundary and prove each job receives only its own repo, token, project ID, and callbacks. Run the same test against a Railway staging project.

### 3. [8/10 High] Canceled and relaunched projects can run in parallel and accept stale callbacks

- **Location**: `graphify/server/routes/launch.py:143-194`, `227-251`, `264-317`, `321-428`.
- **Evidence**: Cancel marks a row `FAILED` but explicitly does not stop the Railway job. Relaunch reuses the same project row and ID, moving it back to `CLONING`. Status, artifact, and usage callbacks authenticate only a global shared secret plus `project_id`; they carry no run ID, sequence number, nonce, idempotency key, or deployment ID. Once the row is relaunched, callbacks from the canceled job are accepted as belonging to the new run. Launch also has no per-user rate or concurrency quota.
- **Attack scenario**: A user repeatedly launches, cancels, and relaunches one project. Old jobs continue spending and, after the row re-enters an in-flight state, can overwrite the new run's status/artifacts. Retries of `/usage` create duplicate rows; arbitrary negative token counts and arbitrary `operation` values are accepted by the current Pydantic model.
- **Impact**: Unbounded parallel Railway/LLM spend, stale or mismatched graphs, incorrect progress, duplicated or corrupt usage accounting, and persistent cross-run data integrity failures.
- **Confidence**: High. The behavior is explicit in the cancel comment and callback data model.
- **Remediation**: Create a distinct immutable run record for every extraction. Require a random per-run callback credential and `run_id`; enforce monotonic state transitions and idempotent event IDs in the database. Reject callbacks whose run is not the project's current run. Cancel/terminate the external job, revoke its callback credential, and cap launches per user/IP/project. Constrain usage fields to allowlisted operations and non-negative bounded token counts.
- **Verification**: Test cancel → relaunch → late old status/artifact/usage callbacks and prove all old events are rejected. Test callback retries and prove exactly one usage event is stored. Confirm remote cancellation stops provider spend.

### 4. [8/10 High] AI daily budget can be bypassed with parallel WebSocket sessions

- **Location**: `graphify/server/budget.py:95-122`; `graphify/server/routes/agent.py:415-462`, `477-593`.
- **Evidence**: Each WebSocket independently calls `check_budget()`, which only sums already-committed usage. The provider call happens afterward and usage is recorded only after streaming completes. There is no reservation row, atomic conditional update, advisory lock, per-user semaphore, or provider-call concurrency cap. The budget module's statement that overshoot is “bounded by one call” is false when a user opens multiple sockets.
- **Attack scenario**: An authenticated user opens N WebSockets for one or more owned projects and sends one message on each before any stream finishes. All N checks see the same below-limit total and all N expensive calls start.
- **Impact**: The user can exceed the daily limit by an attacker-chosen number of calls and drain the shared provider account. Disconnects do not guarantee provider work is canceled or usage is recorded.
- **Confidence**: High. The check/use/record ordering is direct and no compensating control was found.
- **Remediation**: Atomically reserve worst-case cost/tokens before the provider call using a database transaction/row lock or Redis script; refund the unused reservation on completion/failure. Add a small per-user and per-project concurrency limit, plus provider-level hard caps. Record a request ID before starting so disconnects and retries remain accountable.
- **Verification**: Launch 20 simultaneous turns at a budget just below one call's maximum. Assert no more than the configured concurrency starts and total committed plus reserved spend never exceeds the cap.

### 5. [7/10 Medium] Repository and agent side effects are not idempotent or transactionally serialized

- **Location**: `graphify/server/models.py:333-448`; `graphify/server/routes/agent.py:163-171`, `650-692`, `723-808`.
- **Evidence**: `AgentSession` has a unique project constraint, but `_get_or_create_session` performs an unlocked select-then-insert and does not handle `IntegrityError`. Proposal persistence performs select/supersede/insert per path with a commit inside the loop and no constraint guaranteeing one `PROPOSED` row per project/path. PR creation performs external branch/commit/PR side effects before marking rows `COMMITTED`, with no idempotency key or row lock.
- **Attack scenario**: Two browser tabs or retried requests create sessions or proposals concurrently, yielding a 500 or multiple active proposals. Two confirmed PR requests race, create separate branches/commits/PRs from the same proposal set, and both later mark the same rows committed. A concurrent edit can also change stored content while an older snapshot is being pushed.
- **Impact**: Duplicate pull requests, ambiguous change state, partial multi-file persistence, user-visible 500s, and a database record that can disagree with what was committed remotely.
- **Confidence**: High for the race windows; provider behavior determines the exact duplicate artifacts.
- **Remediation**: Add request idempotency keys and durable operation records. Lock selected proposal rows (`FOR UPDATE SKIP LOCKED`) and transition them to `DISPATCHING` before external calls. Add a partial unique index for one proposed change per project/path. Use PostgreSQL upsert/retry for session creation. Commit all proposals for one assistant turn in one transaction. Reconcile partial external failures with a resumable state machine.
- **Verification**: Run barrier-controlled duplicate session, proposal, edit/dispatch, and PR requests. Assert one session, one active proposal per path, one remote PR, and a recoverable state after each injected external failure.

### 6. [7/10 Medium] Artifact, graph, and edit limits permit memory/disk/CPU amplification

- **Location**: `graphify/server/routes/launch.py:74-76`, `321-376`; `graphify/server/routes/projects.py:66-80`; `graphify/server/agent_retrieval.py:34-38`, `45-87`; `graphify/server/routes/agent.py:118-145`, `245-270`.
- **Evidence**: Each artifact may be 256 MB and is synchronously written from an async handler; concurrent uploads can overwrite the same destination non-atomically. JSON fetch/read paths parse entire remote or local artifacts with no response-byte, node, edge, depth, or decompression limit. The NetworkX cache is bounded to eight entries by count, not bytes. `after_content` is unbounded and every read recomputes a full unified diff.
- **Attack scenario**: An authenticated user creates several large projects and requests graph/agent views, causing multiple huge JSON and NetworkX objects to coexist. A very large saved change triggers large database rows and repeated CPU/memory-heavy diffs. Concurrent sandbox uploads block the event loop and readers can observe truncated files.
- **Impact**: Process OOM, event-loop stalls, disk exhaustion, slow database queries, corrupt artifact reads, and denial of service for unrelated users.
- **Confidence**: High for missing bounds; infrastructure-level request limits were not verified.
- **Remediation**: Set global request/body limits at the proxy and ASGI layer. Stream to a random temporary file with async I/O, validate JSON shape/counts, then `fsync` and atomically replace. Reduce and make limits configurable. Bound remote response bytes before JSON parsing. Cache by total bytes with single-flight loading. Cap editable file content and diff work; reject binary/oversized changes.
- **Verification**: Load-test just-below/above-limit artifacts and edits with concurrent clients. Monitor RSS, event-loop latency, disk usage, and cache bytes; verify readers see either the old complete file or the new complete file, never a partial one.

### 7. [6/10 Medium] Admin login limiter is bypassable across replicas and can grow without bound

- **Location**: `graphify/server/routes/admin_auth.py:46-101`, `109-147`.
- **Evidence**: Attempts are stored in a module-global dictionary keyed by the combination of email and client IP. The code documents that it is per-process. Using unique emails or source IPs bypasses accumulation for the real account, and expired entries are removed only when that exact key is checked again; the dictionary has no maximum size or periodic cleanup.
- **Attack scenario**: A distributed attacker rotates IPs against a known admin email to avoid the five-attempt threshold, or sends many syntactically valid unique emails to consume process memory. Multiple workers/replicas multiply the allowed attempts.
- **Impact**: Password brute force and unauthenticated memory denial of service against the admin authentication process.
- **Confidence**: High. Edge/WAF controls may reduce exposure but were not verified.
- **Remediation**: Use a bounded shared Redis/database rate limiter with separate counters for normalized account, IP/network, and global traffic. Trust forwarded client IPs only from an allowlisted proxy. Add TTL-based eviction, jittered backoff, monitoring, and optional MFA for admins.
- **Verification**: Repeat attempts across two workers and rotating IPs; the account-wide limit must still trigger. Flood unique emails and confirm memory remains bounded and entries expire.

### 8. [6/10 Medium] User deletion leaves repository-derived artifacts on disk

- **Location**: `graphify/server/routes/launch.py:345-376`; `graphify/server/routes/admin_data.py:389-408`; `graphify/server/config.py:62-67`.
- **Evidence**: Sandbox graphs and file trees are stored under `workspace-storage/<project_id>`. Admin deletion removes only the database user row and relies on database cascades; it does not delete project directories or invalidate cached graphs. Repository-derived filenames, symbols, topology, and other metadata can therefore outlive the user/project records.
- **Attack scenario**: After account deletion, an operator, backup, later bug, or reused storage mount can still access the former customer's repository-derived artifacts without a database ownership record linking them to retention controls.
- **Impact**: Data-retention/privacy failure and orphaned storage growth; sensitive private-repository metadata may persist indefinitely.
- **Confidence**: High for local storage. External object storage and backup lifecycle are not implemented/verified.
- **Remediation**: Use a transactional deletion workflow: mark deleting, stop runs, revoke tokens, delete artifacts and cache entries, then finalize database deletion. Record deletion outcomes and retry failures. Define retention/backup tombstone behavior.
- **Verification**: Create a project with artifacts, delete its user, and assert database rows, workspace directory, in-memory cache, and any object-store keys are gone or covered by a documented retention tombstone.

### 9. [4/10 Low] Production entrypoint enables reload and omits baseline security headers

- **Location**: `graphify/server/app.py:30-42`, `59-68`.
- **Evidence**: The packaged `graphify-server` entrypoint binds publicly with `reload=True`. The app adds CORS but no trusted-host or security-header middleware. No alternate production process file was found in scope.
- **Attack scenario**: If this entrypoint is used in production, the file watcher/supervisor adds restart and resource behavior inappropriate for a stable service. Responses lack repository-defined HSTS, frame, MIME-sniffing, referrer, permissions, and CSP policy; absent edge configuration, browser hardening depends entirely on external infrastructure.
- **Impact**: Avoidable restart/resource instability and reduced browser defense in depth.
- **Confidence**: Medium because the actual production command and edge headers were not verified.
- **Remediation**: Make reload an explicit development-only option; run a fixed worker command with bounded concurrency/timeouts. Add trusted-host and security-header middleware or document/test equivalent edge headers.
- **Verification**: Inspect the deployed process tree/config and response headers. Change a source file in staging and confirm the production worker does not reload.

### 10. [4/10 Low] Locked toolchain contains two known vulnerable package versions

- **Location**: `uv.lock:1487`, `3161-3162`, `4512-4513`.
- **Evidence**: `pip-audit --local` on 2026-08-01 reported two unique advisories after duplicate output was consolidated: `pip` 26.1.1 (`PYSEC-2026-196`, fixed in 26.1.2) and `setuptools` 82.0.1 (`PYSEC-2026-3447`, fixed in 83.0.0). The versions are present in `uv.lock` and the active environment.
- **Attack scenario**: Exploitability depends on the advisory conditions and whether untrusted packages/build inputs are processed. No reachable runtime exploit was proven in the FastAPI request path.
- **Impact**: Supply-chain/build compromise or toolchain misuse under advisory-specific prerequisites.
- **Confidence**: High for installed versions/advisories; Medium for application reachability.
- **Remediation**: Upgrade to at least the listed fixed versions, regenerate the lock, rebuild images from a clean cache, and rerun the full test/audit suite. Keep build tooling out of the final runtime stage with a multi-stage image.
- **Verification**: `pip-audit` returns no occurrence of either advisory and the final production image does not contain unnecessary build tools.

## Checklist Coverage

| # | Check | Status | Evidence / rationale |
|---:|---|---|---|
| 1 | Secrets exposure | Finding | Finding 1. |
| 2 | Dependency legitimacy | Not verified | Direct dependencies were inspected; registry provenance/maintainer history was not fully verified. |
| 3 | Authentication design | Passed | Signed max-age cookies (`sessions.py:32-52`), Argon2 admin hashing (`admin_sessions.py:41-66`), and separate admin/user secrets. |
| 4 | Security verification evidence | Finding | Backend tests exist, but no concurrency/idempotency tests were found for the agent, PR, or Railway races. |
| 5 | Injection and unsafe execution | Passed | ORM queries are parameterized; sandbox subprocesses use argument arrays (`scripts/sandbox_entrypoint.py:91-104`, `128-141`); no reachable `eval`/shell interpolation found in scope. |
| 6 | Secret-file/artifact exclusions | Finding | Finding 1. |
| 7 | Known vulnerable dependencies | Finding | Finding 10. |
| 8 | Rate limiting and abuse controls | Finding | Findings 3, 4, and 7. |
| 9 | Attack-surface coverage | Finding | Findings 2-6 cover public HTTP/WebSocket and internal callback entry points. |
| 10 | Database authorization | Passed | User/project/change queries consistently scope by trusted user/project IDs, e.g. `projects.py:53-63` and `agent.py:289-301`. |
| 11 | CORS and browser boundary | Passed | Credentialed CORS uses one configured explicit origin (`app.py:34-42`); cookies are HttpOnly/Secure-derived/SameSite Lax. Edge CSRF policy remains a deployment consideration. |
| 12 | Open redirects | Passed | OAuth redirects use configured frontend/backend URLs, not request-controlled destinations (`auth.py:59-69`, `183-194`). |
| 13 | Storage permissions/handling | Finding | Findings 3, 6, and 8. |
| 14 | Sensitive logging | Passed | Provider errors are mapped without raw response bodies; token-bearing clone errors are redacted (`sandbox_entrypoint.py:133-141`). |
| 15 | Third-party webhook authenticity | Not applicable | No payment/provider webhook receiver found; internal sandbox callbacks are covered by Finding 3. |
| 16 | Server-side permissions | Passed | User, project, change, and admin boundaries are enforced in server dependencies/queries. |
| 17 | Dependency audit completion | Finding | Finding 10; local environment audited, production image SBOM not available. |
| 18 | Password reset/account recovery | Not applicable | No reset/recovery flow in reviewed backend. |
| 19 | Error leakage | Passed | Most provider/internal errors are converted to generic client messages; logs retain references. |
| 20 | Session management | Passed | Expiry is verified on every read and inactive accounts are rejected. Server-side revocation beyond account disable/secret rotation is not implemented. |
| 21 | Consistent API protection | Finding | Callback identity/idempotency and WebSocket spend controls are inconsistent with REST ownership controls. |
| 22 | AI cost and tool controls | Finding | Findings 2-5. |
| 23 | Email/SMS infrastructure | Not applicable | No messaging endpoint/provider detected. |
| 24 | Account/data deletion | Finding | Finding 8. |
| 25 | Backups and recovery | Not verified | No authoritative deployment/restore evidence in scope. |
| 26 | Secret rotation | Not verified | Rotation procedures and prior build/image exposure are unknown. |
| 27 | DDoS and edge protection | Not verified | CDN/WAF/gateway configuration was not available. |
| 28 | Upload limits and handling | Finding | Finding 6; a per-file cap exists but parsing, total request, atomicity, and concurrency remain unsafe. |
| 29 | Audit logging | Not verified | Usage events exist, but durable security audit logs for admin credential/user/deletion actions were not found. |
| 30 | Environment separation | Finding | Finding 1; production/preview secret separation is not otherwise verifiable. |

## Passed Checks

| Check | Evidence |
|---|---|
| Tenant/object authorization | Project and change access is scoped at the SQL query boundary. |
| Admin/user principal separation | Different cookie names, salts, signing secrets, dependencies, and database principals. |
| Credential storage | OAuth/LLM tokens use AES-256-GCM with random 96-bit nonces (`crypto.py:18-41`). |
| OAuth state | Random state cookies are constant-time compared and expire after ten minutes. |
| SQL/command injection | SQLAlchemy expressions and subprocess argument lists are used; no confirmed injection sink in reviewed backend. |
| CORS | Credentialed browser API access uses one explicit configured origin rather than `*`. |
| Redirects | Success/error destinations are built from configured application origins. |
| Sensitive provider errors | Raw provider bodies and secrets are not returned to clients. |
| Static quality | Ruff passed. Bandit's six matches were reviewed; false-positive URL “password” matches and intentional exception handling were not promoted to findings. |

## Not Applicable

| Check | Reason |
|---|---|
| Payments/subscriptions | No Stripe, Paystack, Flutterwave, RevenueCat, or entitlement flow detected. |
| Password reset/email/SMS | No password recovery or messaging infrastructure detected. |
| Mobile security | No mobile application code in the reviewed backend scope. |

## Not Verified

| Check | Missing evidence / next step |
|---|---|
| Railway isolation behavior | Reproduce the interleaving against a staging Railway project and capture which variables each deployment snapshots. |
| Built/pushed image history | Inspect registry digests, CI build logs, local/remote build caches, and rotate secrets if any affected context was built. |
| Cloud controls | Provide CDN/WAF/API-gateway rate limits, request-size limits, host validation, and response-header configuration. |
| Database operations | Provide backup/PITR/restore-test evidence, connection limits, least-privilege roles, and environment separation. |
| Provider cost caps | Verify hard AI and Railway spend caps/alerts independently of application accounting. |
| Secret rotation | Provide rotation/revocation runbooks and dates; verify encrypted tokens can be re-keyed. |
| Security audit logging | Provide external audit-log/monitoring configuration for admin and destructive operations. |
| Full tests | The server test suite's session fixture automatically connects to the configured external PostgreSQL database. The run was stopped after connection failure; no live test data was intentionally changed. |

## Prioritized Remediation Plan

1. Immediately fix `.dockerignore`, remove the timestamped secret backup from the repository directory, investigate prior builds, and rotate potentially embedded credentials.
2. Replace shared mutable Railway service-variable orchestration with immutable per-run jobs or a durable serialized queue; introduce run IDs and per-run callback credentials.
3. Implement real remote cancellation, monotonic run-scoped callbacks, callback idempotency, and launch quotas.
4. Make AI budget enforcement atomic with reservations and add per-user/project/provider concurrency caps.
5. Add operation state machines/idempotency keys and database locking/constraints for agent sessions, proposals, and PR dispatch.
6. Bound request, artifact, graph, cache, and edit resources by bytes and structural complexity; make artifact publication atomic.
7. Move admin rate limiting to a bounded shared store and add admin MFA/monitoring.
8. Delete artifacts/caches as part of account/project deletion and document backup retention.
9. Disable production reload, add/test security headers, upgrade audited toolchain packages, and rerun static, dependency, unit, integration, concurrency, and load tests in an isolated test environment.

## Implementation Checklist

Blueprint ready.

### Scope and working definitions

- **Run**: one immutable extraction attempt. Relaunching a project creates a new run; it never reuses the identity or callback credentials of an earlier attempt.
- **Current run**: the only run allowed to update the project's visible progress and published artifacts.
- **Idempotent operation**: repeating the same request or callback has the same durable effect as processing it once.
- **Complete fix**: implementation, migration/configuration, negative-path handling, automated regression tests, and the verification described in the finding are all finished.
- **Release gate**: Findings 1-4 must be complete before production deployment. Findings 2 and 3 are one coordinated run-orchestration change and must not be released separately.

### Phase 0 — Contain immediate exposure

#### Finding 1 — Secrets copied into the Docker image

- [x] Expand `.dockerignore` to exclude `.env`, `.env.*`, `env.backup-*`, `*.pem`, `*.key`, credential JSON, `secrets/`, local databases, logs, caches, and workspace artifacts.
- [ ] Move `env.backup-1785543035` and any other secret backups outside the repository and build context without printing their contents.
- [ ] Add an automated build-context/image canary test that proves ignored secret files are absent from the final filesystem and saved image layers.
- [x] Make the production image multi-stage and confirm build-only tools and secret material are absent from the runtime stage.
- [ ] Inventory local, CI, registry, and Railway builds that may contain the old context.
- [ ] Rotate every potentially exposed credential, prioritizing database, session/admin signing, token encryption, GitHub, Railway, sandbox callback, and LLM credentials.
- [ ] Run a secret scanner against the repository, Docker build context, and exported image without logging secret values.

#### Temporary production controls for Findings 2 and 3

- [ ] Disable Railway tag auto-deploy and manual redeploys for the shared sandbox service.
- [x] Reject a launch while any sandbox run is active globally; keep this fail-closed guard until the queue-backed orchestration is complete.
- [ ] Configure provider and Railway hard-spend caps/alerts as a backstop.

### Phase 1 — Rebuild extraction orchestration around immutable runs

#### Database foundation for Findings 2 and 3

- [x] Add an `ExtractionRun` model and Alembic migration with `id`, `project_id`, lifecycle state, immutable repository inputs, provider/model metadata, external deployment ID, callback-secret hash, timestamps, cancellation fields, and error details.
- [x] Add `Project.current_run_id` and make project progress/artifact fields a projection of the current run rather than the source of run identity.
- [x] Define and enforce monotonic states such as `QUEUED -> STARTING -> CLONING -> INDEXING -> READY`, with terminal `FAILED` and `CANCELED` paths.
- [x] Add database constraints/indexes for one current run per project, one globally active shared-service run, and valid progress/token ranges.
- [ ] Backfill existing projects safely and provide a tested migration downgrade.

#### Finding 2 — Shared mutable Railway configuration

- [x] Change `POST /api/projects` to create and commit a queued run instead of mutating Railway variables inline.
- [x] Add a database-backed worker that claims queued runs with `FOR UPDATE SKIP LOCKED` and serializes the singleton Railway service for the full deployment lifetime.
- [x] Pass `run_id` and the run-specific callback credential to Railway; never identify an operation from `project_id` or “latest deployment” alone.
- [x] Correlate and persist the exact deployment ID before accepting deployment-specific actions; fail closed when correlation cannot be proven.
- [x] Prevent another run from replacing service variables until the active deployment has reached a verified terminal state.
- [x] Make worker crashes recoverable: leases/heartbeats expire, abandoned claims are reconciled, and retries do not create a second deployment.
- [ ] Add barrier-controlled tests that interleave two projects at every Railway API boundary and prove repository, token, LLM key, run, deployment, and callback isolation.
- [ ] Repeat the concurrency test against a Railway staging project.

#### Finding 3 — Cancellation, stale callbacks, and duplicate usage

- [x] Generate a random callback credential per run, store only its hash, and require both `run_id` and the credential on status, artifact, and usage callbacks.
- [x] Add a unique callback `event_id` and a durable callback-event table/constraint so retries are processed exactly once.
- [x] Reject callbacks for canceled, terminal, unknown, or non-current runs; old runs must never update current project state.
- [x] Validate callback transitions in a transaction with a row lock; reject regressions and out-of-order terminal updates.
- [x] Constrain usage operations to an allowlist and token counts to non-negative configured bounds.
- [x] Bind every artifact and usage row to `(project_id, run_id)` and publish artifacts only after the run is still confirmed current.
- [x] Implement real Railway deployment cancellation and revoke the run callback credential before returning success.
- [x] Add per-user, per-project, and global launch quotas with clear `409`/`429` responses.
- [x] Test cancel -> relaunch -> late old status/artifact/usage callbacks and prove all stale events are rejected.
- [ ] Test callback retries and concurrent duplicates and prove exactly one usage/artifact event is committed.
- [ ] Verify remote cancellation stops the container and provider spend.

### Phase 2 — Make AI spend enforcement atomic

#### Finding 4 — Raceable daily AI budget

- [ ] Add a durable `BudgetReservation`/LLM request record with a unique request ID, user/project, reserved cost, committed cost, state, and expiry.
- [ ] Calculate a conservative maximum call cost from model pricing and configured input/output limits before invoking the provider.
- [ ] Atomically lock the user's daily budget row (or use an equivalent conditional update), include active reservations in the total, and reject a reservation that would exceed the cap.
- [ ] Add per-user and per-project concurrent-turn limits enforced in the same transaction.
- [ ] Commit actual usage against the reservation and refund the unused amount on success, failure, timeout, or cancellation.
- [ ] Reconcile expired/incomplete reservations so a process crash neither leaks allowance nor loses billable usage.
- [ ] Ensure WebSocket disconnect cancels provider work where supported and still finalizes the request/accounting record.
- [ ] Test 20 simultaneous turns just below the maximum-call boundary and prove started concurrency and `committed + reserved` spend never exceed policy.
- [ ] Test failures, disconnects, worker crashes, retries, and unlimited-budget mode.

### Phase 3 — Serialize agent and repository side effects

#### Finding 5 — Non-idempotent sessions, proposals, and PR creation

- [ ] Make agent-session creation an upsert/retry path that safely handles the existing unique project constraint.
- [ ] Add a partial unique index allowing only one `PROPOSED` change per `(project_id, path)`.
- [ ] Persist all proposals from one assistant turn in one transaction; remove the per-file commits.
- [ ] Add `DISPATCHING` and failure/retry states to the change/operation lifecycle.
- [ ] Require a client idempotency key for PR creation and persist a durable dispatch operation before external API calls.
- [ ] Lock selected proposal rows and transition them to `DISPATCHING` before creating a branch.
- [ ] Snapshot and hash the exact proposed contents used by the dispatch so concurrent edits cannot change an in-flight commit.
- [ ] Persist branch, commit, and PR identifiers after each external step so a retry resumes/reconciles instead of duplicating work.
- [ ] Add recovery behavior for branch-only, commit-only, and PR-created/database-commit-failed states.
- [ ] Test simultaneous session creation, proposal replacement, editing/dispatch, duplicate PR requests, and an injected failure after every provider step.
- [ ] Prove one session, one active proposal per path, one remote PR, and a resumable durable state.

### Phase 4 — Bound artifacts, graph loading, caching, and edits

#### Finding 6 — Resource amplification

- [ ] Add configurable proxy and ASGI request/body limits, plus per-user/project storage quotas.
- [ ] Lower/configure artifact size limits and add maximum JSON nodes, edges, nesting depth, string length, and decompressed bytes.
- [ ] Stream uploads asynchronously to a random file in the target filesystem, validate them, `fsync`, and atomically replace the published artifact.
- [ ] Reject concurrent/out-of-date uploads by checking the current `run_id` immediately before atomic publication.
- [ ] Bound remote graph responses while streaming, before calling `response.json()` or loading the entire body.
- [ ] Validate local and remote graph/file JSON against an explicit schema before NetworkX construction.
- [ ] Replace count-only graph caching with total-byte accounting, TTL/eviction, and single-flight loads per project/run.
- [ ] Cap editable file size, proposal `after_content`, number of files per turn, total proposal bytes, and diff computation work; reject binary content.
- [ ] Move CPU-heavy parsing/diff work off the event loop or enforce a bounded executor.
- [ ] Add above/below-limit concurrent load tests and record RSS, event-loop latency, disk usage, cache bytes, and response behavior.
- [ ] Prove readers observe either the old complete artifact or the new complete artifact, never a partial file.

### Phase 5 — Replace the admin login limiter

#### Finding 7 — Per-process, unbounded login attempts

- [ ] Implement a bounded shared PostgreSQL or Redis limiter with separate normalized-account, IP/network, and global buckets.
- [ ] Add TTL expiry, bounded storage/periodic cleanup, jittered backoff, and security metrics/alerts.
- [ ] Trust forwarded client addresses only from explicitly configured proxy networks.
- [ ] Preserve uniform unknown-account/wrong-password timing and responses.
- [ ] Add an admin MFA requirement or document and schedule it as a release prerequisite.
- [ ] Test rotating IPs against one account across two app workers and prove the account bucket still locks.
- [ ] Flood unique valid emails and prove limiter storage and process memory remain bounded and entries expire.

### Phase 6 — Make deletion complete and recoverable

#### Finding 8 — Orphaned repository artifacts

- [ ] Add a durable deletion workflow/state: mark deleting, block new work, cancel active runs, and revoke repository/run credentials.
- [ ] Delete project artifact directories through validated project-specific paths only; never construct a recursive target from an unchecked value.
- [ ] Invalidate graph/file caches and delete object-store keys before finalizing the database deletion.
- [ ] Record each deletion step, retry transient failures, and surface permanently failed cleanup to administrators.
- [ ] Define backup retention/tombstone behavior and verify it with the actual backup provider.
- [ ] Test deleting users with ready, failed, and active projects and assert database rows, local files, cached graphs, external jobs, and object-store keys are gone or explicitly tombstoned.

### Phase 7 — Production hardening and dependency cleanup

#### Finding 9 — Reload and missing browser headers

- [ ] Make reload opt-in for development; the packaged production entrypoint must run without a watcher.
- [ ] Define the production worker count, concurrency, graceful-shutdown timeout, request timeout, and WebSocket shutdown behavior.
- [ ] Add trusted-host validation.
- [ ] Add HSTS (HTTPS production only), frame-ancestors/frame protection, `X-Content-Type-Options`, Referrer Policy, Permissions Policy, and a tested CSP compatible with the frontend.
- [ ] Document whether each header is owned by the application or edge and add an integration test for the deployed response.
- [ ] Change a source file in staging and prove the production process does not reload.

#### Finding 10 — Vulnerable locked build tools

- [ ] Raise the minimum `pip` to `26.1.2` or newer and `setuptools` to `83.0.0` or newer where they are explicitly installed/locked.
- [ ] Regenerate `uv.lock` from a clean environment and review the dependency diff.
- [ ] Rebuild production and sandbox images without cache.
- [ ] Run `pip-audit` against the locked environment and final images and prove the two cited advisories are absent.
- [ ] Confirm unnecessary build tools are not present in the final runtime image.

### Cross-cutting verification and release gates

- [ ] Add an isolated PostgreSQL test database owned by the test suite; tests must never use a developer or production database URL.
- [ ] Add deterministic concurrency helpers/barriers so race regressions do not depend on timing sleeps.
- [ ] Run migrations up/down/up on an anonymized production-shaped dataset.
- [ ] Run Ruff, type checking, Bandit, pip-audit, unit tests, integration tests, concurrency tests, and resource/load tests.
- [ ] Add security audit events for admin authentication, run cancellation, callback rejection, PR dispatch, and user deletion without logging credentials or repository tokens.
- [ ] Document new environment variables, queue/worker operation, callback rotation, cancellation, recovery, retention, and incident procedures.
- [ ] Verify provider/Railway spend caps, alerts, WAF/request limits, backups/PITR, restore tests, least-privilege database roles, and environment separation.
- [ ] Re-run the security audit and close every finding with links to code, migration, test, and operational evidence.
- [ ] Permit production deployment only after Findings 1-4 pass their gates; schedule Findings 5-10 before declaring the remediation complete.

### Finding coverage tracker

| Finding | Primary phase | Status | Release evidence |
|---:|---|---|---|
| 1 | Phase 0 | [~] Code containment complete; operations pending | Docker layer canary, image scan, rotation record |
| 2 | Phase 1 | [~] Core implementation complete; verification pending | Full Railway interleaving test and staging proof |
| 3 | Phase 1 | [~] Core implementation complete; verification pending | Concurrent usage/artifact duplicate proof and remote cancellation proof |
| 4 | Phase 2 | [ ] Not started | 20-way budget concurrency test |
| 5 | Phase 3 | [ ] Not started | Duplicate-side-effect and recovery tests |
| 6 | Phase 4 | [ ] Not started | Boundary/load results and atomic-read proof |
| 7 | Phase 5 | [ ] Not started | Multi-worker/rotating-IP and bounded-memory tests |
| 8 | Phase 6 | [ ] Not started | End-to-end deletion evidence |
| 9 | Phase 7 | [ ] Not started | Staging process/header verification |
| 10 | Phase 7 | [ ] Not started | Clean lock/image dependency audit |

### Recommended implementation slices

1. **Containment PR** — Finding 1, temporary shared-service launch guard, production reload default, and dependency upgrades.
2. **Run schema PR** — `ExtractionRun`, callback events, project current-run pointer, state-transition helpers, and migrations.
3. **Orchestration PR** — queue worker, Railway serialization/correlation/cancellation, run-scoped callbacks, quotas, and concurrency tests.
4. **Budget PR** — reservations, atomic limits, request accounting, concurrency caps, and WebSocket cancellation handling.
5. **Agent idempotency PR** — session upsert, proposal constraints/transactions, dispatch state machine, and PR reconciliation.
6. **Resource PR** — streaming/atomic artifacts, graph validation, byte-bounded cache, edit/diff limits, and load tests.
7. **Operations PR** — shared admin limiter, deletion workflow, headers, audit logging, runbooks, and final audit evidence.

Implementation should begin only after this checklist and its definitions are confirmed; application code remains unchanged by this planning step.

## Deployment Incident Addendum — 2026-08-01

### Local sandbox-image build

The reported build failure occurs before any project layer is built. Docker cannot resolve `auth.docker.io` while requesting the pull token for `python:3.12-slim`, so this is a Docker Desktop/host DNS, VPN, proxy, firewall, or network-filtering failure—not a `Dockerfile.sandbox` syntax or Python-base-image failure. Confirm resolution for both `auth.docker.io` and `registry-1.docker.io`, then prove the transport independently with `docker pull python:3.12-slim` before retrying the project build. Do not clear build caches for this symptom; the cache is unrelated.

### Railway crash state

The supplied `"  - Java"` information-level record is an ordinary output fragment, not the terminating exception. Railway's useful evidence is the first `[sandbox] FATAL:` or `[sandbox] FAILED:` line and the final process exit code. Locally, starting `scripts/sandbox_entrypoint.py` without deployment inputs deterministically logs `[sandbox] FATAL: REPO_URL is not set` and exits 2 (`scripts/sandbox_entrypoint.py:269-273`).

The image is a batch entrypoint (`Dockerfile.sandbox:48`) that requires the backend to write `REPO_URL` and `PROJECT_ID` immediately before triggering a deployment. Switching the Railway source, pressing Redeploy, or enabling image auto-updates starts the image outside that backend-controlled sequence. Before any backend launch, such a start has no inputs, exits 2, and Railway correctly marks it Crashed. After a backend launch, the inputs are not truly “per deploy”: `variableCollectionUpsert` has persisted the last run's values in the shared service configuration. A later manual or automatic redeploy can therefore rerun the previous project with stale repository credentials and LLM key. Auto-update should be disabled for this per-run service; publish an immutable version/digest and roll it out only through a controlled idle/deployment procedure.

No checked-in GitHub Actions workflow builds or pushes `Dockerfile.sandbox`: `publish.yml` publishes PyPI and `release-graph.yml` publishes a graph asset. Railway image auto-update monitors a registry tag after another process pushes a new digest; it does not rebuild this repository. Until a build-and-push workflow is added, every source change requires an explicit local/CI build, tag, and push.

The screenshot's empty registry-credential section is acceptable only if the GHCR package is public. A private package requires a read-capable GHCR credential. Because the service produced container output, image-pull authentication is unlikely to be the current runtime crash, but the full untruncated image reference and digest should still be verified.

### Production concurrency consequence

Railway services are singleton deployments by default, while the backend uses one shared service and replaces its complete variable collection before each launch (`graphify/server/sandbox.py:114-160`). Image-source deployment does not change that control-plane behavior. Concurrent jobs can overwrite one another's inputs and a new deployment can supersede a running one. The production-safe design is an always-on, queue-backed worker or genuinely isolated per-run services/jobs with immutable input and a unique run ID—not parallel redeployments of one mutable Railway service. Until that redesign is complete, serialize launches with a distributed lock, reject concurrent work, disable tag auto-deploy, and bind every callback and artifact to a unique run ID.
