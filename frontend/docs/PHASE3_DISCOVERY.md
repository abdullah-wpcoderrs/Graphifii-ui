# Phase 3 Discovery: Current State vs Major Updates

**Date:** 2026-07-31

**Phase 3 Scope:** Dashboard refactor with sidebar, real data integration, integrations (OAuth), admin LLM credentials, and workspace graph wiring.

---

## Current State: What Exists

### Backend (Python/FastAPI in `graphify/server/`)

**Completed (Phases 0-2):**
- ✅ `config.py` — environment validation (DATABASE_URL, secrets, GitHub credentials)
- ✅ `db.py` — async SQLAlchemy engine + session factory
- ✅ `models.py` — `User`, `GitHubInstallation`, `Project` SQLAlchemy ORM models
- ✅ `crypto.py` — AES-256-GCM encrypt/decrypt for GitHub tokens at rest
- ✅ `sessions.py` — signed session cookies (itsdangerous) + OAuth state management
- ✅ `app.py` — FastAPI app with CORS + `/health` endpoint
- ✅ `routes/auth.py` — `/api/auth/github/login`, `/callback`, `/api/session`, `/api/auth/logout`
- ✅ `github_client.py` — OAuth token exchange + user profile fetch

**Not Yet Implemented:**
- Project CRUD endpoints (`GET /api/projects`, `/api/projects/:id`, etc.)
- GitHub repository listing (`GET /api/repositories`)
- Integrations listing + connection APIs (`GET/POST /api/integrations`)
- Admin LLM credentials CRUD (`GET/POST/PUT/DELETE /api/admin/credentials`)
- GitLab OAuth client
- GitBucket OAuth client
- Sandbox provisioning (`POST /api/projects/launch`)
- WebSocket streaming for provisioning status
- Graph querying endpoints
- File tree endpoints

### Graphify Core (`graphify/graphify/llm.py`)

**Existing LLM Support** (already implemented):
- ✅ `claude` (Anthropic) — `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` env vars
- ✅ `gemini` (Google) — `GEMINI_API_KEY`, `GOOGLE_API_KEY` env vars
- ✅ `openai` (OpenAI) — `OPENAI_API_KEY`, `OPENAI_MODEL` env vars
- ✅ Plus: kimi, ollama, deepseek, azure, bedrock (optional)

The `llm.py` module exposes:
- Provider registry with env key mappings
- Token counting (tiktoken-based)
- Model defaults + pricing info
- Vision support flags
- Temperature/max_tokens configs

**Not Yet Exposed to Admin UI:**
- No database model for storing encrypted admin credentials
- No REST API to configure which LLM provider to use
- No client-side encryption before sending keys to backend

### Frontend (Next.js/React in `frontend/app/`)

**Completed:**
- ✅ Authentication screens (`/`, `/auth/error`, `/onboarding/github`)
- ✅ Dashboard layout (fixture-based)
- ✅ Workspace UI (3-pane with Monaco, React Flow, agent)
- ✅ Component library (Graphify colors, typography, tokens)

**Not Yet Implemented:**
- Authenticated layout wrapper with sidebar
- Real data fetching (all screens use fixtures)
- Repositories screen
- Integrations screen
- Admin settings screen
- Service adapter layer (`app/lib/api.ts`)

---

## Major Updates: What We're Building (Phase 3)

### Backend Changes

#### 1. **LLM Credentials Admin API**

**File:** `graphify/server/routes/admin.py` (NEW)

Endpoints:
- `GET /api/admin/credentials` — list available/configured LLM providers (admin-only)
- `POST /api/admin/credentials` — save encrypted LLM key (frontend sends encrypted value)
- `PUT /api/admin/credentials/:provider` — update existing key
- `DELETE /api/admin/credentials/:provider` — remove key
- `POST /api/admin/credentials/verify` — test if key is valid (call LLM API with a test prompt)

**Database Model Update:** Add `SystemCredential` table to `models.py`:
```python
class SystemCredential(Base):
    __tablename__ = "system_credentials"
    
    id: UUID = primary key
    provider: str  # "openai", "anthropic", "gemini"
    key_ciphertext: str  # encrypted key from frontend
    key_iv: str  # IV for decryption
    created_at: datetime
    updated_at: datetime
```

**Migration:** Add alembic migration for `system_credentials` table.

#### 2. **GitLab OAuth Integration**

**File:** `graphify/server/github_client.py` (EXTEND) → `graphify/server/git_clients.py` (RENAME & EXTEND)

New class: `GitLabOAuthClient`
- Exchange code for token (GitLab OAuth v2)
- Fetch user profile (GET `/api/v4/user`)
- Return structured response matching the GitHub pattern

**Env Vars Required:**
```env
GITLAB_CLIENT_ID=<from gitlab.com/admin/applications>
GITLAB_CLIENT_SECRET=<generated>
GITLAB_WEBHOOK_SECRET=<random hex>
```

#### 3. **GitBucket OAuth Integration**

**File:** `graphify/server/git_clients.py` (EXTEND)

New class: `GitBucketOAuthClient`
- Exchange code for token (GitBucket OAuth)
- Fetch user profile
- Return structured response

**Env Vars Required:**
```env
GITBUCKET_CLIENT_ID=<from gitbucket instance>
GITBUCKET_CLIENT_SECRET=<generated>
GITBUCKET_WEBHOOK_SECRET=<random hex>
```

#### 4. **Integration Connection Routes**

**File:** `graphify/server/routes/integrations.py` (NEW)

Endpoints:
- `GET /api/integrations` — list available integrations + connection status
- `GET /api/integrations/:provider/login` — start OAuth flow (redirect to provider)
- `GET /api/integrations/:provider/callback` — handle OAuth callback, store token
- `POST /api/integrations/:provider/disconnect` — revoke token, remove connection
- `GET /api/integrations/:provider/repos` — list repos from connected provider

**Data Model:** Extend `User` model to track connected integrations:
```python
class User(Base):
    # ... existing fields ...
    
    # New OAuth token fields (encrypted, like GitHub)
    gitlab_access_token_ciphertext: str | None
    gitlab_access_token_iv: str | None
    gitbucket_access_token_ciphertext: str | None
    gitbucket_access_token_iv: str | None
```

#### 5. **Project CRUD & Graph Endpoints**

**File:** `graphify/server/routes/projects.py` (EXTEND existing)

New endpoints:
- `POST /api/projects` — create project from repo (trigger provisioning)
- `GET /api/projects/:id/graph` — fetch graph.json
- `GET /api/projects/:id/files` — fetch file tree
- `WS /ws/projects/:id` — WebSocket for provisioning status updates (Phase 4)

#### 6. **Sandbox Provisioning (Railway)**

**File:** `graphify/server/sandbox.py` (NEW)

Architecture:
- User clicks "Launch Workspace" on a repo
- Backend calls `POST /api/projects` with repo URL
- Backend creates ephemeral Railway job:
  - Clones repo into `/workspace` volume
  - Runs graphify extraction (`graphify extract /workspace`)
  - Streams progress via WebSocket
  - Stores graph.json + file tree in S3/R2 or local storage (for now, local)
  - Updates `Project.status` to `READY`

**Implementation:**
- Use Railway API client (httpx) to create ephemeral jobs
- Job runs Python 3.12 with graphify CLI
- Volume mounts `/workspace` for code + outputs
- Env vars passed: `ANTHROPIC_API_KEY` (or active LLM key from `SystemCredential`)

---

### Frontend Changes

#### 1. **Authenticated Layout with Sidebar**

**File:** `app/(authenticated)/layout.tsx` (NEW)

- Imports `<Sidebar />`
- Renders floating inset sidebar (6px border-radius)
- Responsive: persistent on desktop, drawer on mobile (<768px)

#### 2. **Sidebar Component**

**File:** `app/components/sidebar.tsx` (NEW)

Features:
- Navigation to `/dashboard`, `/repositories`, `/integrations`, `/admin/settings` (admin-only)
- User avatar + name from `/api/session`
- Logout button → `POST /api/auth/logout`
- Collapse toggle (stores state in localStorage)
- Mobile: hamburger menu → slide-out drawer

#### 3. **Admin Settings Screen**

**File:** `app/(authenticated)/admin/settings/page.tsx` (NEW)

Features:
- **LLM Credentials Section:**
  - Display 3 cards: OpenAI, Anthropic (Claude), Gemini
  - Each card shows: provider name, icon, status (configured/empty), model preview
  - Click card → modal to add/edit key
  - Modal:
    - Input field for API key
    - Select model dropdown (populated from provider registry)
    - "Test Connection" button (calls backend verify endpoint)
    - "Save" button (encrypts client-side before sending)
    - Shows success/error toast

- **Client-Side Encryption** (Web Crypto API, AES-256-GCM with PBKDF2):
  ```ts
  // Before sending to backend
  const encrypted = await encryptApiKey(plainKey, USER_PASSWORD_OR_MASTER_SECRET);
  // POST /api/admin/credentials with {provider, ciphertext, iv, salt}
  ```

**Permissions:**
- Only admins (role === "ADMIN" from `/api/session`) can access `/admin/settings`
- Redirect non-admins to `/dashboard`

#### 4. **Integrations Screen (Extended)**

**File:** `app/(authenticated)/integrations/page.tsx` (ENHANCE)

Display 3 integration cards:

**GitHub Card:**
- Status: Connected (✓ badge)
- Action buttons: "Manage Repos" or "Disconnect"
- Shows: `user.github_login`

**GitLab Card:**
- Status: Not Connected (○ badge)
- Action button: "Connect with GitLab" → redirects to `/api/integrations/gitlab/login`
- After OAuth callback → stores token, shows "Connected" state
- Action buttons: "Manage Repos" or "Disconnect"

**GitBucket Card:**
- Status: Not Connected (○ badge)
- Action button: "Connect with GitBucket" → redirects to `/api/integrations/gitbucket/login`
- After OAuth callback → stores token, shows "Connected" state
- Action buttons: "Manage Repos" or "Disconnect"

**Error Handling:**
- If env vars not set (`GITLAB_CLIENT_ID`, etc.): show grayed-out card with tooltip "Not configured by administrator"
- If OAuth fails: redirect to `/auth/error?code=integration_connection_failed&ref=...`
- If token is invalid on list repos: show "Connection expired, please reconnect"

#### 5. **Repositories Screen (Multi-Source)**

**File:** `app/(authenticated)/repositories/page.tsx` (REFACTOR)

- Tabs or filter dropdown: GitHub | GitLab | GitBucket | All
- Fetch repos from connected integrations:
  ```ts
  const repos = await Promise.all([
    fetchGitHubRepos(),
    fetchGitLabRepos(),  // if connected
    fetchGitBucketRepos(),  // if connected
  ]);
  ```
- Show all repos in unified list
- "Launch Workspace" button per repo → `POST /api/projects` with repo URL + provider

#### 6. **Service Adapter Layer (Extended)**

**File:** `app/lib/api.ts` (EXTEND)

New functions:
```ts
// Integrations
export async function fetchIntegrations() { }  // list providers + status
export async function startIntegrationOAuth(provider: string) { }  // redirect to /api/integrations/:provider/login
export async function disconnectIntegration(provider: string) { }  // POST /api/integrations/:provider/disconnect
export async function fetchGitLabRepos() { }  // GET /api/integrations/gitlab/repos
export async function fetchGitBucketRepos() { }  // GET /api/integrations/gitbucket/repos

// Admin credentials
export async function fetchAdminCredentials() { }  // GET /api/admin/credentials (admin-only)
export async function saveAdminCredential(provider, encryptedKey) { }  // POST /api/admin/credentials
export async function verifyAdminCredential(provider) { }  // POST /api/admin/credentials/verify
export async function deleteAdminCredential(provider) { }  // DELETE /api/admin/credentials/:provider
```

#### 7. **Encryption Utility**

**File:** `app/lib/crypto.ts` (NEW)

Implement client-side AES-256-GCM encryption (per PRD):
```ts
export async function encryptApiKey(
  plainKey: string,
  masterSecret: string
): Promise<{ciphertext: string; iv: string; salt: string}> {
  // PBKDF2 key derivation from masterSecret
  // AES-256-GCM encryption
  // Return base64-encoded ciphertext, iv, salt
}

export async function decryptApiKey(
  ciphertext: string,
  iv: string,
  salt: string,
  masterSecret: string
): Promise<string> {
  // Reverse of above (client-only, for preview/testing)
}
```

---

## Decision Points for Agent Review

Before implementing Phase 3, the agent should:

1. **Review `graphify/graphify/llm.py`** and confirm:
   - Which providers to expose (Anthropic, OpenAI, Gemini confirmed)
   - How to map env var names to provider IDs
   - Pricing/model info structure

2. **Review GitHub App OAuth Flow** (in `BACKEND_IMPLEMENTATION_CHECKLIST.md`) and apply same pattern to:
   - GitLab OAuth app setup (what scopes to request)
   - GitBucket OAuth app setup

3. **Review Railway Docker/Sandbox Setup** and confirm:
   - How to call Railway API to create ephemeral jobs
   - Volume mounting strategy for `/workspace`
   - Logging/status streaming back to frontend

4. **Review Web Crypto API Standards** for AES-256-GCM encryption:
   - PBKDF2 iteration count (100k recommended)
   - Salt/IV generation
   - Base64 encoding

---

## Implementation Sequence (Recommended Order)

1. **Backend Project Routes** — GET/POST `/api/projects`, list + create
2. **Backend GitHub Repos** — GET `/api/repositories` (extend existing GitHub client)
3. **Backend Integrations Routes** — OAuth flows for GitLab/GitBucket
4. **Database Migrations** — Add `SystemCredential` + integration token fields to `User`
5. **Backend Admin API** — POST/GET/DELETE `/api/admin/credentials`
6. **Frontend Service Adapters** — Create `app/lib/api.ts` with all endpoint calls
7. **Frontend Authenticated Layout** — Create `(authenticated)` layout group
8. **Frontend Sidebar** — Floating inset component with navigation
9. **Frontend Admin Settings** — LLM credentials CRUD + encryption
10. **Frontend Integrations Screen** — OAuth login + connection status
11. **Frontend Repositories Screen** — Multi-source repo listing
12. **End-to-End Testing** — Local browser testing, error scenarios

---

## Testing & Verification Approach

- **Unit tests** for encryption/decryption utilities
- **TestClient tests** for all new backend endpoints
- **Browser E2E tests** for OAuth flows (GitHub, GitLab, GitBucket)
- **Error scenarios** — missing env vars, expired tokens, invalid credentials
- **Responsive testing** — sidebar drawer on mobile
- **Permission testing** — admin-only routes block non-admins

---

## Known Unknowns & Deferred Decisions

- **Sandbox provisioning** (Phase 4) — exact Railway API integration strategy
- **Token refresh rotation** (Phase 5) — how to auto-rotate expired GitHub/GitLab tokens
- **WebSocket streaming** (Phase 4) — `/ws/projects/:id` for real-time provisioning status
- **Graph querying** (Phase 6) — how to wire `POST /api/agent/query` to graphify engine
