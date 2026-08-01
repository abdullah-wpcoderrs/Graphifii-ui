# Railway setup — extraction sandbox provisioning

The Graphify backend launches an **ephemeral Railway job** for each project:
it clones the repository, runs `graphify extract /workspace`, writes
`graph.json` + `files.json`, and reports progress back to the backend. This
guide creates the Railway project and produces the five environment values
the backend needs.

**Result of this guide** — five values for `graphify/.env`:

```
RAILWAY_API_TOKEN=
RAILWAY_PROJECT_ID=
RAILWAY_SERVICE_ID=
RAILWAY_ENVIRONMENT_ID=
SANDBOX_CALLBACK_SECRET=
```

Until all of them are set, `POST /api/projects` returns **503** with a clear
"not configured" message rather than failing confusingly — you can develop
everything else before doing this.

---

## Step 1 — Create the Railway account and project

1. Sign up at <https://railway.app> (GitHub sign-in is easiest, and you already
   have a GitHub App configured for this project).
2. Railway's free trial is limited; sandbox jobs need real build minutes, so
   expect to add a payment method on the **Hobby** plan for anything beyond a
   couple of test runs.
3. From the dashboard choose **New Project → Empty Project**.
4. Name it something unambiguous, e.g. `graphify-sandbox`.

## Step 2 — Get `RAILWAY_PROJECT_ID`

Open the project. The browser URL is:

```
https://railway.app/project/<PROJECT_ID>
```

Copy the UUID after `/project/`. That is `RAILWAY_PROJECT_ID`.

## Step 3 — Create the sandbox service

The service is the container template each extraction run deploys.

1. Inside the project: **New → Empty Service** (not "Deploy from GitHub" — the
   backend injects the repo to clone at deploy time as `REPO_URL`, so the
   service itself must not be pinned to one repository).
2. Name it `graphify-extractor`.
3. Open the service → **Settings → Source**, and point it at the Graphify
   image or repo that contains the extraction entrypoint. It needs Python 3.12
   plus tree-sitter, and must run `graphify extract /workspace` on start.
4. Under **Settings → Deploy**, set the start command if it is not already
   baked into the image.

### Step 3a — Get `RAILWAY_SERVICE_ID`

With the service open, the URL becomes:

```
https://railway.app/project/<PROJECT_ID>/service/<SERVICE_ID>
```

Copy the UUID after `/service/`.

### Step 3b — Get `RAILWAY_ENVIRONMENT_ID`

Railway projects have environments (`production` by default). The id appears
in the URL as `?environmentId=<UUID>` when you switch environments, or via the
GraphQL API in Step 5. Copy that UUID.

## Step 4 — Create `RAILWAY_API_TOKEN`

1. Go to **Account Settings → Tokens** (<https://railway.app/account/tokens>).
2. **Create Token**. Scope it to the `graphify-sandbox` project — a
   project-scoped token that leaks cannot touch your other Railway projects.
3. Copy it immediately; Railway shows it once.

Treat this like a password: it can deploy and delete infrastructure. It
belongs in `.env` (gitignored) and in your host's secret store — never in a
commit.

## Step 5 — Verify the IDs before wiring them in

Confirm all three IDs are real and mutually consistent, so a typo surfaces
here rather than as an opaque Railway error during a launch:

```bash
curl -s https://backboard.railway.app/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"query { me { projects { edges { node { id name environments { edges { node { id name } } } services { edges { node { id name } } } } } } } }"}' | python3 -m json.tool
```

The response lists each project with its `id`, its environments, and its
services. Match them against what you copied from the URLs.

## Step 6 — Generate the callback secret

The sandbox reports progress to
`POST /api/internal/projects/{id}/status`. That endpoint is authenticated by
a shared secret, compared with `hmac.compare_digest`:

```bash
openssl rand -hex 32
```

Put the result in `SANDBOX_CALLBACK_SECRET`. The backend passes it to each job
as `GRAPHIFY_CALLBACK_SECRET`, and the job must send it back as the
`X-Sandbox-Secret` header. **If this is unset the callback endpoint is
disabled (503)** — deliberately, because an unauthenticated version would let
anyone mark any project `READY` and point its `graph_json_url` at a URL of
their choosing, which the workspace would then fetch and render.

## Step 7 — Fill in `.env` and restart

```
RAILWAY_API_TOKEN=<step 4>
RAILWAY_PROJECT_ID=<step 2>
RAILWAY_SERVICE_ID=<step 3a>
RAILWAY_ENVIRONMENT_ID=<step 3b>
SANDBOX_CALLBACK_SECRET=<step 6>
```

Restart the backend. `POST /api/projects` should now attempt a real deploy
instead of returning 503.

---

## Building the sandbox image

### Step A — Build locally

Start Docker Desktop first, then from `graphify/`:

```bash
docker build -f Dockerfile.sandbox -t graphify-sandbox:latest .
```

Railway runs **linux/amd64**. On an Intel Mac that is what you build natively.
On Apple Silicon you must cross-build or the image will not start on Railway:

```bash
docker build --platform linux/amd64 -f Dockerfile.sandbox -t graphify-sandbox:latest .
```

### Step B — Test the container locally (do this before Railway)

The container talks to the backend over plain HTTP, so you can exercise the
entire extraction pipeline on your laptop with **no Railway and no tunnel**.
This separates "is my container correct?" from "is my Railway wiring
correct?" — debugging both at once is what makes this step feel impossible.

Create a project row to report against, then:

```bash
docker run --rm \
  -e REPO_URL="https://github.com/octocat/Hello-World.git" \
  -e PROJECT_ID="<a real project uuid>" \
  -e GRAPHIFY_CALLBACK_URL="http://host.docker.internal:8000/api/internal/projects/<uuid>/status" \
  -e GRAPHIFY_CALLBACK_SECRET="<SANDBOX_CALLBACK_SECRET from .env>" \
  -e OPENAI_API_KEY="<optional — skips community labeling if absent>" \
  graphify-sandbox:latest
```

`host.docker.internal` is how a container reaches the host on Docker Desktop
(on Linux, add `--add-host=host.docker.internal:host-gateway`). Watch the
backend log: you should see `CLONING → INDEXING → READY` callbacks arrive and
an artifact upload land in `workspace-storage/<project-id>/`.

If this works, the container is correct and anything that fails afterwards is
Railway configuration.

### Step C — Push to a registry (GHCR)

A registry is online storage for Docker images. Railway cannot see your local
Docker daemon, so the image has to live somewhere Railway can download it
from. We use GHCR (GitHub Container Registry) because the project already has
a GitHub account.

#### C1 — Create an access token

GitHub needs proof it is really you before letting you upload.

1. github.com → **Settings** → **Developer settings** → **Personal access
   tokens** → **Tokens (classic)** → **Generate new token (classic)**.
2. Tick the **`write:packages`** scope. (That automatically includes
   `read:packages`, which is what lets an image be pulled back down.)
3. Generate, then copy the token immediately — GitHub displays it exactly
   once and you cannot retrieve it later.

Treat it like a password: it can publish packages under your account. Do not
commit it.

#### C2 — Log in to the registry

```bash
echo "PASTE_YOUR_TOKEN_HERE" | docker login ghcr.io -u <your-github-username> --password-stdin
```

`--password-stdin` pipes the token in rather than typing it as an argument,
which keeps it out of your shell history and out of the process list where
other programs on the machine could read it.

Expect: `Login Succeeded`.

#### C3 — Tag and push

"Tagging" renames the local image to include the registry address, which is
how Docker knows where to upload it.

```bash
docker tag graphify-sandbox:latest ghcr.io/<your-github-username>/graphify-sandbox:latest
docker push ghcr.io/<your-github-username>/graphify-sandbox:latest
```

The image is roughly 600MB, so the first push takes a few minutes. Later
pushes are much faster — Docker only uploads the layers that changed.

#### C4 — Make the package public (easy to miss)

**New GHCR packages are private by default, and Railway cannot download a
private image.** The symptom is confusing: the Railway deploy simply never
starts, usually with no clear error explaining why.

1. Your GitHub profile → **Packages** → **graphify-sandbox**.
2. **Package settings** → **Change visibility** → **Public**.

Public here exposes only the built image, not your source repository. If the
image must stay private instead, give Railway a pull credential under
Service → Settings → Source → private registry credentials.

#### C5 — Verify the push worked

```bash
docker manifest inspect ghcr.io/<your-github-username>/graphify-sandbox:latest > /dev/null && echo "image is reachable"
```

Run this *after* making the package public. If it fails with `unauthorized` or
`denied`, the package is still private and Railway will fail the same way.

#### Re-pushing after code changes

The image is a snapshot — editing `sandbox_entrypoint.py` locally does not
change what Railway runs. After any change to the entrypoint or to the
graphify package, rebuild and push again:

```bash
docker build -f Dockerfile.sandbox -t graphify-sandbox:latest .
docker tag graphify-sandbox:latest ghcr.io/<your-github-username>/graphify-sandbox:latest
docker push ghcr.io/<your-github-username>/graphify-sandbox:latest
```

Because the tag stays `latest`, Railway picks up the new image on its next
deploy. Visibility only has to be set once.

### Step D — Point the Railway service at the image

In the `graphify-extractor` service:

1. **Settings → Source → Image** — set `ghcr.io/<you>/graphify-sandbox:latest`.
   If you originally created it from a repo, switch the source to an image.
2. **Settings → Deploy → Restart Policy: Never.** This is a batch job that
   exits when finished; the default restart policy would treat a *successful*
   exit as a crash and re-run the extraction in a loop.
3. Leave **Variables** empty. The backend injects everything per deploy (see
   the table below) — anything set here is a static fallback, and stale values
   silently override what you expect.
4. Do **not** assign a public domain. Nothing connects to this container; it
   makes outbound calls only.

---

## What the backend sends the job

`launch_project_on_railway()` injects these env vars per deploy:

| Variable | Purpose |
| --- | --- |
| `REPO_URL` | Repository to clone |
| `PROJECT_ID` | Included in the progress callback URL |
| `REPO_TOKEN` | User's decrypted git token — only set for private repos |
| `<PROVIDER>_API_KEY` | Admin-configured LLM key, e.g. `OPENAI_API_KEY` |
| `GRAPHIFY_CALLBACK_URL` | Where to POST progress |
| `GRAPHIFY_CALLBACK_SECRET` | Sent back as `X-Sandbox-Secret` |
| `WORKSPACE_STORAGE_TYPE` | `local` or `s3` |

The job is expected to POST progress as it goes:

```bash
curl -X POST "$GRAPHIFY_CALLBACK_URL" \
  -H "X-Sandbox-Secret: $GRAPHIFY_CALLBACK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"status":"INDEXING","progress_percent":40,"message":"Parsing sources"}'
```

and finish with a terminal status:

```bash
-d '{"status":"READY","progress_percent":100,"graph_json_url":"<url>"}'
# or
-d '{"status":"FAILED","error":"clone failed: repository not found"}'
```

Valid `status` values are `CLONING`, `INDEXING`, `READY`, `FAILED`. Callbacks
arriving after a project is already terminal are ignored, so a job that keeps
running after the user cancels cannot resurrect it.

---

## Caveats worth knowing before you rely on this

- **`BACKEND_URL` must be reachable from Railway.** The callback URL is built
  from it, so a `localhost` value works only if the sandbox runs on your
  machine. For local development against a real Railway job, expose the
  backend with a tunnel (ngrok/cloudflared) and set `BACKEND_URL` to that
  public URL.
- **The GraphQL mutation in `sandbox.py` is unverified against a live
  account.** It was written from Railway's documented
  `serviceInstanceDeploy` shape but has never been executed — Railway has no
  plain "run a one-off job" REST endpoint, and the exact input shape is the
  most likely thing to need adjusting on first real run. Expect to iterate
  here; that is the first thing to check if a launch fails.
- **Secrets reach the job as environment variables.** The LLM key and the
  user's git token are visible to anything running inside that container.
  That is inherent to this design; it is safe only as long as the container
  runs Graphify's own image and nothing user-supplied.
- **Sandbox teardown is not implemented.** Jobs are expected to exit on their
  own; cancellation marks the project failed in the database but does not stop
  the Railway job (Phase 7 scope).
- **Cost scales with launches.** Every "Launch Workspace" is a container
  build+run. Watch the Railway usage dashboard once real users can trigger it.
