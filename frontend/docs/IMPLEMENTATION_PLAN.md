# Implementation Plan — Graphify Dashboard Refactor with Sidebar & Real Data Integration

**Status:** Phase 3 — Dashboard, Sidebar, Repositories, Integrations (OAuth), Admin Settings (LLM Credentials), Workspace Real Data Wiring

**Last Updated:** 2026-07-31

---

## Pre-Implementation Review (Agent Instructions)

**Before starting implementation, the agent MUST:**

1. **Review existing graphify codebase:**
   - Read `graphify/graphify/llm.py` to understand supported providers (Claude/Anthropic, Gemini, OpenAI) and how env vars map to providers
   - Review `graphify/graphify/cli.py` to understand extraction workflow and API
   - Check `graphify/docs/how-it-works.md` for extraction and querying architecture

2. **Review standard procedures from backend docs:**
   - Read `graphify/docs/github-app-setup.md` for OAuth pattern and environment variable strategy
   - Review Phase 2 implementation (`graphify/server/routes/auth.py`) to understand session + redirect patterns
   - Check database migration patterns in `alembic/versions/` folder

3. **Confirm Railway sandbox strategy:**
   - How does Railway API create ephemeral jobs?
   - What volume mounts are available for `/workspace`?
   - How are env vars passed to sandbox containers?

4. **Confirm encryption libraries:**
   - Frontend: Web Crypto API (AES-256-GCM with PBKDF2) — no external packages
   - Backend: `cryptography` library (already in pyproject.toml)

5. **Discuss with user:**
   - Are GitLab and GitBucket OAuth apps already created? What are the client IDs/secrets?
   - Should sandbox provisioning use Railway or a different platform?
   - Should graph.json be stored in S3/R2 or locally for now?

---

## What we are building

A complete dashboard refactor that introduces authenticated-area layout architecture with a floating inset sidebar (6px border radius) providing persistent navigation to Dashboard, Repositories, and Integrations screens. All screens will fetch real data from the backend (authenticated user's projects, GitHub repositories, integration status), render explicit empty states, and the Workspace will wire to live graph data from the graphify engine. Six new backend endpoints (`GET /api/projects`, `/api/projects/:id`, `/api/repositories`, `/api/integrations`, `/api/projects/:id/graph`, `/api/projects/:id/files`) and three frontend screens will replace all mock data fixtures with real API calls.

---

## Language we agreed on

- **Dashboard**: The authenticated hub showing user's recent/active projects after login, nested inside a shared layout with sidebar navigation.
- **Floating Inset Sidebar**: A persistent left nav with 6px border radius, inset styling (overlay inside main area, not flush), navigates to Dashboard, Repositories, Integrations, and Logout. Collapses to drawer on mobile.
- **Graph engine**: Existing graphify backend (POST /api/extract, POST /api/query in sandboxed FastAPI sidecars). We wire frontend to it, don't build the chunking/querying service.
- **Empty states only**: No mock data fallback. All screens have explicit "no data" UI. Clean up all fixtures.
- **Real data**: Dashboard shows recent projects from DB; Repositories lists GitHub repos via authenticated user's token; Integrations shows available platforms (GitHub connected, GitBucket/GitLab placeholders).

---

## Decisions made

- **Phase scope**: Dashboard + Repositories + Integrations + Sidebar + Workspace graph wiring all ship together in one phase. This is justified because they all share the same authenticated session context, sidebar navigation, and backend integration patterns.

- **Sidebar architecture**: Shared layout wrapper at `app/(authenticated)/layout.tsx` renders the floating inset sidebar once alongside a `<main>` content area. All three screens (`/dashboard`, `/repositories`, `/integrations`) nest as route segments inside `(authenticated)`, avoiding code duplication and keeping navigation state consistent.

- **Backend endpoints**: All six ship in this phase:
  - `GET /api/projects` — list user's projects (with recent-first sort)
  - `GET /api/projects/:id` — fetch project details (name, repo, status, graph URLs)
  - `GET /api/repositories` — fetch user's GitHub repos via authenticated token
  - `GET /api/integrations` — hardcoded list of available integrations + connection status
  - `GET /api/projects/:id/graph` — fetch graph.json for the workspace graph viewer
  - `GET /api/projects/:id/files` — fetch file tree for the workspace explorer

- **Data fetching**: Create service adapters (`app/lib/api.ts` or `app/services/`) to replace direct fixture imports. Adapters handle credential passing, error mapping, and fallback to empty states (not fixtures).

- **Workspace refactor**: Wire existing workspace components to real data. Replace `workspace-fixtures.ts` calls with `GET /api/projects/:id` + `GET /api/projects/:id/graph` + `GET /api/projects/:id/files`. Keep the three-pane layout, Monaco, React Flow, agent intact.

- **Mobile sidebar**: On <768px, sidebar becomes a collapsible drawer or hamburger-triggered slide-out. Desktop remains always-visible floating inset panel.

---

## Assumptions

- Backend is running at `NEXT_PUBLIC_API_URL` and `/api/session` returns authenticated user (already verified in Phase 2).
- GitHub repositories are fetched server-side using the user's encrypted token (backend holds GitHub OAuth token, frontend never sees it).
- Integrations list is hardcoded in the backend (no dynamic provider registry yet).
- Graph data exists in S3/R2 or is generated on-demand by the graphify engine; workspace just fetches the URL or JSON blob.
- Mobile breakpoint is 768px; below that, sidebar becomes drawer.

---

## Backend Implementation (Python/FastAPI in `graphify/graphify/server/`)

### 3.0 Database Model Updates

**File:** `graphify/server/models.py` (EXTEND)

Add new models:

1. **SystemCredential** — encrypted LLM provider keys:
   ```python
   class SystemCredential(Base):
       __tablename__ = "system_credentials"
       
       id: UUID = primary key
       provider: str  # "openai", "anthropic", "gemini"
       key_ciphertext: str  # encrypted with TOKEN_ENCRYPTION_KEY
       key_iv: str
       key_salt: str  # for future PBKDF2 support
       created_at: datetime
       updated_at: datetime
   ```

2. **Extend User model** — add integration tokens:
   ```python
   class User(Base):
       # ... existing fields ...
       
       # GitLab OAuth tokens (encrypted)
       gitlab_access_token_ciphertext: str | None
       gitlab_access_token_iv: str | None
       gitlab_user_id: int | None
       gitlab_login: str | None
       
       # GitBucket OAuth tokens (encrypted)
       gitbucket_access_token_ciphertext: str | None
       gitbucket_access_token_iv: str | None
       gitbucket_user_id: int | None
       gitbucket_login: str | None
   ```

**Alembic Migration:**
- Create `alembic/versions/<timestamp>_add_system_credentials_and_integrations.py`
- Add `system_credentials` table
- Add `gitlab_*` and `gitbucket_*` columns to `users` table

### 3.1 Extend `graphify/server/github_client.py` → Rename to `graphify/server/git_clients.py`

Rename the file and add new classes:

**GitLabOAuthClient:**
- `exchange_code_for_token(code, redirect_uri)` → calls GitLab OAuth endpoint
- `fetch_gitlab_user(access_token)` → calls `GET /api/v4/user`
- Separate exceptions: `GitLabAuthError`, `GitLabUnavailableError`

**GitBucketOAuthClient:**
- `exchange_code_for_token(code, redirect_uri)` → calls GitBucket OAuth endpoint
- `fetch_gitbucket_user(access_token)` → calls user profile endpoint
- Separate exceptions: `GitBucketAuthError`, `GitBucketUnavailableError`

**Config Updates** (`config.py`):
- Add env vars: `GITLAB_CLIENT_ID`, `GITLAB_CLIENT_SECRET`, `GITLAB_WEBHOOK_SECRET`
- Add env vars: `GITBUCKET_CLIENT_ID`, `GITBUCKET_CLIENT_SECRET`, `GITBUCKET_WEBHOOK_SECRET`
- Validate that at least one integration client ID is set (or provide safe defaults)

### 3.2 Create `graphify/server/routes/projects.py`

Implement project-listing and project-detail endpoints:

- `GET /api/projects` — query `Project` table where `user_id = current_user.id`, order by `updated_at DESC`, return:
  ```json
  [
    {
      "id": "uuid",
      "repo_name": "owner/repository",
      "repo_url": "https://github.com/...",
      "status": "READY|CLONING|INDEXING|FAILED",
      "graph_json_url": "https://...",
      "graph_html_url": "https://...",
      "created_at": "2026-07-31T...",
      "updated_at": "2026-07-31T..."
    }
  ]
  ```

- `GET /api/projects/:id` — fetch single project, verify ownership, return full project record (same schema as above).

- `GET /api/projects/:id/graph` — fetch graph.json from S3/R2 or sidecar container, return JSON blob. Handle 404 if graph not yet generated.

- `GET /api/projects/:id/files` — fetch file tree from sidecar or S3, return hierarchical JSON:
  ```json
  {
    "id": "root",
    "name": "repository",
    "type": "directory",
    "children": [...]
  }
  ```

### 3.2 Create `graphify/server/routes/github.py`

Implement GitHub repository listing:

- `GET /api/repositories` — use user's decrypted GitHub token from `User.github_access_token_*` (via `crypto.decrypt()`), call GitHub API (`GET https://api.github.com/user/repos?per_page=100`), return:
  ```json
  [
    {
      "id": 12345,
      "name": "repository-name",
      "full_name": "owner/repository-name",
      "html_url": "https://github.com/owner/repository-name",
      "description": "...",
      "default_branch": "main",
      "stargazers_count": 42
    }
  ]
  ```
  Handle token expiry; if expired, skip refresh for now (Phase 5), return 401 with safe error message.

### 3.3 Create `graphify/server/routes/integrations.py`

Implement OAuth flows for GitLab and GitBucket, plus integration status tracking:

- **`GET /api/integrations`** — return list with connection status:
  ```json
  [
    {
      "id": "github",
      "name": "GitHub",
      "status": "connected",
      "icon": "github",
      "login": "user-github-login"
    },
    {
      "id": "gitlab",
      "name": "GitLab",
      "status": "connected" | "not_configured" | "not_connected",
      "icon": "gitlab",
      "login": "user-gitlab-login or null",
      "message": "Admin has not configured GitLab OAuth (missing GITLAB_CLIENT_ID)"
    },
    {
      "id": "gitbucket",
      "name": "GitBucket",
      "status": "connected" | "not_configured" | "not_connected",
      "icon": "gitbucket",
      "login": "user-gitbucket-login or null",
      "message": "Admin has not configured GitBucket OAuth"
    }
  ]
  ```

- **`GET /api/integrations/:provider/login`** (provider = `gitlab` or `gitbucket`)
  - Generate OAuth state, set as cookie
  - Redirect to provider's authorize URL

- **`GET /api/integrations/:provider/callback`** (provider = `gitlab` or `gitbucket`)
  - Verify state, exchange code for token
  - Fetch user profile
  - Encrypt token via `crypto.py`, store in `User.{provider}_access_token_*`
  - Redirect to `FRONTEND_URL/integrations` with success indicator
  - On failure: redirect to `FRONTEND_URL/auth/error?code=integration_connection_failed&ref=...`

- **`POST /api/integrations/:provider/disconnect`** (provider = `gitlab` or `gitbucket`)
  - Verify current user, delete tokens from `User` record
  - Return `{"ok": true}`
  - Handles safe logout if token is invalid

- **`GET /api/integrations/:provider/repos`** (provider = `gitlab` or `gitbucket`)
  - Use user's decrypted token to call provider API
  - GitLab: `GET /api/v4/projects?owned=true`
  - GitBucket: equivalent endpoint for user repos
  - Return: `[{id, name, full_name, html_url, description, default_branch, ...}]`
  - Handle 401 on expired token: return safe error message

### 3.4 Create `graphify/server/routes/admin.py`

Implement admin-only endpoints for LLM credentials (CRUD):

- **`GET /api/admin/credentials`** (admin-only)
  - Return list of configured providers with status:
    ```json
    [
      {
        "provider": "openai",
        "configured": true,
        "model": "gpt-4-turbo",
        "updated_at": "2026-07-31T..."
      },
      {
        "provider": "anthropic",
        "configured": false,
        "model": null,
        "message": "No API key configured"
      }
    ]
    ```

- **`POST /api/admin/credentials`** (admin-only)
  - Payload: `{provider, key_ciphertext, key_iv, key_salt}` (frontend sends encrypted)
  - Decrypt using `TOKEN_ENCRYPTION_KEY` to validate structure (no plain key touch)
  - Store in `SystemCredential` table
  - Return `{"ok": true, "provider": "..."}`

- **`PUT /api/admin/credentials/:provider`** (admin-only)
  - Update existing credential
  - Same payload/validation as POST
  - Return `{"ok": true}`

- **`DELETE /api/admin/credentials/:provider`** (admin-only)
  - Remove credential from database
  - Return `{"ok": true}`

- **`POST /api/admin/credentials/verify`** (admin-only)
  - Payload: `{provider}` (no key sent, retrieves from DB)
  - Call LLM API with a simple test prompt ("Say 'ok'")
  - Return `{"ok": true, "model": "..."}`
  - On failure: return `{"ok": false, "error": "API key is invalid or expired"}`

**Authentication & Authorization:**
- All routes require `@get_current_user` dependency
- Check `current_user.role == Role.ADMIN` and return 403 if not
- Log credential updates for audit trail

### 3.5 Create `graphify/server/sandbox.py` (Railway Integration)

Implement ephemeral sandbox provisioning on Railway:

- **`launch_project_on_railway(project_id, repo_url, active_llm_provider)`**
  - Call Railway API to create ephemeral job
  - Mount `/workspace` volume
  - Environment: pass repo URL, active LLM key from `SystemCredential`, project ID
  - Run: `graphify extract /workspace` in container
  - Stream logs/progress back via WebSocket (Phase 4)
  - On completion: store graph.json in local storage or S3 (TBD), update `Project.status = READY`

**Env Vars Required:**
- `RAILWAY_API_TOKEN` (for Railway API calls)
- `WORKSPACE_STORAGE_TYPE` (local|s3) — where to store graph outputs

**Note:** Full provisioning flow (WebSocket, status updates) deferred to Phase 4. For Phase 3, focus on the basic Railway job creation.

### 3.6 Wire routers into `app.py`

```python
from graphify.server.routes.projects import router as projects_router
from graphify.server.routes.github import router as github_router
from graphify.server.routes.integrations import router as integrations_router
from graphify.server.routes.admin import router as admin_router

app.include_router(projects_router)
app.include_router(github_router)
app.include_router(integrations_router)
app.include_router(admin_router)
```

### 3.5 Add `get_current_user` dependency

All endpoints in the three routers must use `get_current_user` (already defined in `sessions.py`) as a dependency to ensure they only return data for the authenticated user.

### 3.6 Test all endpoints

Use FastAPI `TestClient` (no real GitHub calls for now; mock token decryption if needed):
- `GET /api/projects` returns list or empty array
- `GET /api/projects/:id` returns project or 404
- `GET /api/repositories` returns repos or 401 on token issues
- `GET /api/integrations` returns hardcoded list
- `GET /api/projects/:id/graph` returns JSON or 404
- `GET /api/projects/:id/files` returns tree or 404

---

## Frontend Implementation (Next.js/React in `frontend/app/`)

### 4.1 Reorganize routes into `(authenticated)` layout group

Move authenticated routes into a layout group:

```
frontend/app/
├── (authenticated)/
│   ├── layout.tsx          (NEW: sidebar + main layout)
│   ├── dashboard/
│   │   ├── page.tsx        (REFACTOR: real data)
│   │   └── loading.tsx
│   ├── repositories/
│   │   ├── page.tsx        (NEW)
│   │   └── loading.tsx
│   ├── integrations/
│   │   ├── page.tsx        (NEW)
│   │   └── loading.tsx
│   └── workspace/
│       └── [projectId]/
│           ├── page.tsx    (REFACTOR: real data wiring)
│           ├── launch/
│           │   └── page.tsx
│           └── loading.tsx
├── page.tsx                (keep: auth screen)
├── auth/
│   └── error/page.tsx      (keep)
├── onboarding/
│   └── github/page.tsx     (keep)
└── ...
```

### 4.2 Create `app/(authenticated)/layout.tsx`

Renders the floating inset sidebar and main content area:

```tsx
import { Sidebar } from '@/app/components/sidebar';
import { ReactNode } from 'react';

export default function AuthenticatedLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <div className="flex h-screen bg-app">
      <Sidebar />
      <main className="flex-1 overflow-auto flex flex-col">
        {children}
      </main>
    </div>
  );
}
```

### 4.3 Create `app/components/sidebar.tsx`

Floating inset sidebar with navigation:

- Fixed width (~280px on desktop, collapsed on mobile)
- Positioned inset from left with 6px border radius (`border-radius: 6px`)
- Inset box shadow: `box-shadow: inset 0 0 20px rgba(0,0,0,0.3)`
- Contains:
  - Graphify logo/branding at top
  - Nav links to:
    - `/dashboard` (Recent Projects)
    - `/repositories` (Repositories)
    - `/integrations` (Integrations)
    - `/admin/settings` (Admin Settings) — only if `user.role === "ADMIN"`
  - Active state highlighting via `usePathname()`
  - Bottom card with:
    - User avatar (from `/api/session`)
    - User name
    - Logout button (POST `/api/auth/logout`)
    - Collapse/expand icon (stores state in localStorage: `sidebar-collapsed`)
- Mobile (<768px): hamburger toggle → slide-out drawer (not persistent)

### 4.4 Refactor `app/(authenticated)/dashboard/page.tsx`

Shows recent/active projects:

```tsx
'use client';

import { useEffect, useState } from 'react';
import { fetchProjects } from '@/app/lib/api';
import { ProjectCard } from '@/app/components/project-card';
import { EmptyState } from '@/app/components/empty-state';

export default function DashboardPage() {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await fetchProjects();
        setProjects(data);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <DashboardSkeleton />;
  if (error) return <ErrorState message={error} />;
  if (!projects.length) {
    return (
      <EmptyState
        title="No projects yet"
        description="Visit Repositories to launch a new project."
        action={{ label: 'Go to Repositories', href: '/repositories' }}
      />
    );
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-6">Recent Projects</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {projects.map((p) => (
          <ProjectCard key={p.id} project={p} />
        ))}
      </div>
    </div>
  );
}
```

### 4.5 Create `app/(authenticated)/repositories/page.tsx`

Shows all GitHub repositories:

```tsx
'use client';

import { useEffect, useState } from 'react';
import { fetchRepositories } from '@/app/lib/api';
import { RepositoryRow } from '@/app/components/repository-row';
import { EmptyState } from '@/app/components/empty-state';

export default function RepositoriesPage() {
  const [repos, setRepos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const data = await fetchRepositories();
        setRepos(data);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const filtered = repos.filter((r) =>
    r.full_name.toLowerCase().includes(search.toLowerCase())
  );

  if (loading) return <RepositoriesSkeleton />;
  if (error) return <ErrorState message={error} />;
  if (!repos.length) {
    return (
      <EmptyState
        title="No repositories connected"
        description="Visit GitHub settings to grant Graphify access to your repositories."
      />
    );
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-6">Repositories</h1>
      <input
        type="text"
        placeholder="Search repositories..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="mb-4 px-4 py-2 rounded-lg bg-input border border-subtle"
      />
      <div className="space-y-2">
        {filtered.map((r) => (
          <RepositoryRow key={r.id} repo={r} />
        ))}
      </div>
    </div>
  );
}
```

### 4.6 Create `app/(authenticated)/integrations/page.tsx` (Enhanced)

Shows available integrations with OAuth connection flows:

```tsx
'use client';

import { useEffect, useState } from 'react';
import { fetchIntegrations, disconnectIntegration } from '@/app/lib/api';
import { IntegrationCard } from '@/app/components/integration-card';
import { ErrorState } from '@/app/components/error-state';

export default function IntegrationsPage() {
  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await fetchIntegrations();
        setIntegrations(data);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleConnect = (provider) => {
    // Redirect to /api/integrations/:provider/login
    window.location.assign(`${process.env.NEXT_PUBLIC_API_URL}/api/integrations/${provider}/login`);
  };

  const handleDisconnect = async (provider) => {
    try {
      await disconnectIntegration(provider);
      // Refetch integrations to update UI
      const data = await fetchIntegrations();
      setIntegrations(data);
    } catch (err) {
      setError(err.message);
    }
  };

  if (loading) return <IntegrationsSkeleton />;
  if (error) return <ErrorState message={error} />;

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-6">Integrations</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {integrations.map((i) => (
          <IntegrationCard 
            key={i.id} 
            integration={i}
            onConnect={() => handleConnect(i.id)}
            onDisconnect={() => handleDisconnect(i.id)}
          />
        ))}
      </div>
    </div>
  );
}
```

**Integration States:**
- Connected: Shows user login, "Manage Repos" + "Disconnect" buttons
- Not Connected: Shows "Connect with [Provider]" button
- Not Configured: Shows grayed-out card with message "Not configured by administrator" (admin hasn't set env vars)

### 4.7 Create `app/(authenticated)/admin/settings/page.tsx` (NEW)

Admin-only page for managing LLM credentials:

Features:
- Check `user.role === "ADMIN"` from `/api/session`; redirect to `/dashboard` if not admin
- Display 3 sections (tabs or cards): **OpenAI**, **Anthropic (Claude)**, **Gemini**
- Each section shows:
  - Provider name + icon
  - Status badge: "Configured" (✓) or "Not Configured" (○)
  - Model preview (if configured)
  - "Configure" button → open modal

**Modal Flow:**
1. User clicks "Configure"
2. Shows form with:
   - "API Key" input field (placeholder: "Enter your API key")
   - "Model" dropdown (populated from provider options, e.g., gpt-4-turbo for OpenAI)
   - "Master Secret" input (used for client-side encryption, derived from user's session or a fixed org-wide secret)
   - "Test Connection" button (calls backend verify)
   - "Save" button
   - "Cancel" button
3. On "Save":
   - Client-side encrypt API key using `encryptApiKey(apiKey, masterSecret)`
   - POST `/api/admin/credentials` with `{provider, key_ciphertext, key_iv, key_salt}`
   - Show success toast
   - Close modal
4. On "Delete":
   - DELETE `/api/admin/credentials/:provider`
   - Remove from UI
5. On "Test Connection":
   - POST `/api/admin/credentials/verify` with `{provider}`
   - Show result in UI

```tsx
'use client';

import { useEffect, useState } from 'react';
import { fetchAdminCredentials, saveAdminCredential, verifyAdminCredential, deleteAdminCredential } from '@/app/lib/api';
import { encryptApiKey } from '@/app/lib/crypto';
import { LLMCredentialCard } from '@/app/components/llm-credential-card';
import { LLMCredentialModal } from '@/app/components/llm-credential-modal';

const PROVIDERS = ['openai', 'anthropic', 'gemini'];

export default function AdminSettingsPage() {
  const [credentials, setCredentials] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedProvider, setSelectedProvider] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await fetchAdminCredentials();
        setCredentials(Object.fromEntries(data.map(c => [c.provider, c])));
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleSave = async (provider, apiKey, masterSecret, model) => {
    try {
      const encrypted = await encryptApiKey(apiKey, masterSecret);
      await saveAdminCredential(provider, encrypted);
      setCredentials(prev => ({...prev, [provider]: {provider, configured: true, model}}));
      setSelectedProvider(null);
    } catch (err) {
      setError(err.message);
    }
  };

  if (loading) return <div>Loading...</div>;

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-6">Admin Settings</h1>
      <div className="mb-8">
        <h2 className="text-lg font-semibold mb-4">LLM Credentials</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {PROVIDERS.map(provider => (
            <LLMCredentialCard 
              key={provider}
              provider={provider}
              credential={credentials[provider]}
              onConfigure={() => setSelectedProvider(provider)}
            />
          ))}
        </div>
      </div>
      {selectedProvider && (
        <LLMCredentialModal 
          provider={selectedProvider}
          onSave={handleSave}
          onClose={() => setSelectedProvider(null)}
        />
      )}
    </div>
  );
}
```

### 4.8 Create `app/lib/crypto.ts` (Client-Side Encryption)

Implement Web Crypto API encryption (AES-256-GCM with PBKDF2):

```ts
/**
 * Client-side encryption for LLM API keys before sending to backend.
 * Uses AES-256-GCM with PBKDF2 key derivation (per PRD).
 */

const ITERATIONS = 100000;  // PBKDF2 iterations (industry standard)
const SALT_LENGTH = 16;      // bytes
const IV_LENGTH = 12;        // bytes (standard for GCM)

export interface EncryptedKey {
  ciphertext: string;  // base64
  iv: string;          // base64
  salt: string;        // base64
}

/**
 * Encrypt an API key using AES-256-GCM.
 * @param plainKey The plain API key
 * @param masterSecret User-provided or org-wide secret for key derivation
 */
export async function encryptApiKey(
  plainKey: string,
  masterSecret: string
): Promise<EncryptedKey> {
  const enc = new TextEncoder();
  
  // Derive AES key from master secret using PBKDF2
  const keyMaterial = await window.crypto.subtle.importKey(
    'raw',
    enc.encode(masterSecret),
    { name: 'PBKDF2' },
    false,
    ['deriveKey']
  );

  const salt = window.crypto.getRandomValues(new Uint8Array(SALT_LENGTH));
  const key = await window.crypto.subtle.deriveKey(
    {
      name: 'PBKDF2',
      salt,
      iterations: ITERATIONS,
      hash: 'SHA-256',
    },
    keyMaterial,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt']
  );

  // Encrypt the key
  const iv = window.crypto.getRandomValues(new Uint8Array(IV_LENGTH));
  const encrypted = await window.crypto.subtle.encrypt(
    { name: 'AES-GCM', iv },
    key,
    enc.encode(plainKey)
  );

  return {
    ciphertext: Buffer.from(encrypted).toString('base64'),
    iv: Buffer.from(iv).toString('base64'),
    salt: Buffer.from(salt).toString('base64'),
  };
}

/**
 * Decrypt an API key (client-only, for testing/preview).
 * @param encrypted The encrypted key object
 * @param masterSecret The original master secret
 */
export async function decryptApiKey(
  encrypted: EncryptedKey,
  masterSecret: string
): Promise<string> {
  const enc = new TextEncoder();
  const dec = new TextDecoder();

  const keyMaterial = await window.crypto.subtle.importKey(
    'raw',
    enc.encode(masterSecret),
    { name: 'PBKDF2' },
    false,
    ['deriveKey']
  );

  const key = await window.crypto.subtle.deriveKey(
    {
      name: 'PBKDF2',
      salt: new Uint8Array(Buffer.from(encrypted.salt, 'base64')),
      iterations: ITERATIONS,
      hash: 'SHA-256',
    },
    keyMaterial,
    { name: 'AES-GCM', length: 256 },
    false,
    ['decrypt']
  );

  const decrypted = await window.crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: new Uint8Array(Buffer.from(encrypted.iv, 'base64')) },
    key,
    Buffer.from(encrypted.ciphertext, 'base64')
  );

  return dec.decode(decrypted);
}
```

### 4.9 Create `app/lib/api.ts` (or `app/services/api-client.ts`)

Service adapters for all backend calls:

```ts
import { getPublicApiUrl } from './env';
import { EncryptedKey } from './crypto';

async function fetchWithAuth(endpoint: string, init?: RequestInit) {
  const url = `${getPublicApiUrl()}${endpoint}`;
  const response = await fetch(url, {
    credentials: 'include',
    ...init,
  });

  if (!response.ok) {
    throw new Error(`${response.status}: ${response.statusText}`);
  }

  return response.json();
}

// ========== Projects ==========
export async function fetchProjects() {
  return fetchWithAuth('/api/projects');
}

export async function fetchProject(id: string) {
  return fetchWithAuth(`/api/projects/${id}`);
}

export async function fetchProjectGraph(id: string) {
  return fetchWithAuth(`/api/projects/${id}/graph`);
}

export async function fetchProjectFiles(id: string) {
  return fetchWithAuth(`/api/projects/${id}/files`);
}

// ========== Repositories ==========
export async function fetchRepositories() {
  return fetchWithAuth('/api/repositories');
}

export async function fetchGitHubRepos() {
  return fetchWithAuth('/api/repositories?provider=github');
}

export async function fetchGitLabRepos() {
  return fetchWithAuth('/api/integrations/gitlab/repos');
}

export async function fetchGitBucketRepos() {
  return fetchWithAuth('/api/integrations/gitbucket/repos');
}

// ========== Integrations ==========
export async function fetchIntegrations() {
  return fetchWithAuth('/api/integrations');
}

export async function disconnectIntegration(provider: string) {
  return fetchWithAuth(`/api/integrations/${provider}/disconnect`, {
    method: 'POST',
  });
}

// ========== Admin Credentials ==========
export async function fetchAdminCredentials() {
  return fetchWithAuth('/api/admin/credentials');
}

export async function saveAdminCredential(
  provider: string,
  encrypted: EncryptedKey
) {
  return fetchWithAuth('/api/admin/credentials', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      provider,
      key_ciphertext: encrypted.ciphertext,
      key_iv: encrypted.iv,
      key_salt: encrypted.salt,
    }),
  });
}

export async function verifyAdminCredential(provider: string) {
  return fetchWithAuth('/api/admin/credentials/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider }),
  });
}

export async function deleteAdminCredential(provider: string) {
  return fetchWithAuth(`/api/admin/credentials/${provider}`, {
    method: 'DELETE',
  });
}
```

### 4.8 Refactor `app/(authenticated)/workspace/[projectId]/page.tsx`

Wire to real data instead of fixtures:

```tsx
'use client';

import { useEffect, useState } from 'react';
import {
  fetchProject,
  fetchProjectGraph,
  fetchProjectFiles,
} from '@/app/lib/api';
import { WorkspaceShell } from '@/app/components/workspace-shell';
import { ErrorState } from '@/app/components/error-state';

export default function WorkspacePage({
  params,
}: {
  params: { projectId: string };
}) {
  const [project, setProject] = useState(null);
  const [graph, setGraph] = useState(null);
  const [files, setFiles] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const [p, g, f] = await Promise.all([
          fetchProject(params.projectId),
          fetchProjectGraph(params.projectId),
          fetchProjectFiles(params.projectId),
        ]);
        setProject(p);
        setGraph(g);
        setFiles(f);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [params.projectId]);

  if (loading) return <WorkspaceSkeleton />;
  if (error) return <ErrorState message={error} />;
  if (!project) return <ErrorState message="Project not found" />;

  return (
    <WorkspaceShell
      project={project}
      graph={graph}
      files={files}
    />
  );
}
```

### 4.9 Delete or archive fixture files

Remove or archive:
- `app/lib/dashboard.ts`
- `app/lib/workspace-fixtures.ts`

Replace all imports with service adapter calls.

### 4.10 Ensure responsive sidebar

Use CSS media queries or React state to:
- Desktop (≥768px): sidebar always visible, floating inset
- Mobile (<768px): sidebar hidden by default, hamburger toggle → slide-out drawer

### 4.11 Create empty state components

- `app/components/empty-state.tsx` — generic empty state with title, description, optional action button
- Use across Dashboard, Repositories, Workspace (if no files)

### 4.12 Create new components for integrations and admin settings

- **`IntegrationCard.tsx`** — displays a single integration with status badge
  - Props: `integration`, `onConnect`, `onDisconnect`
  - States: Connected (user login shown), Not Connected, Not Configured (grayed out)
  
- **`LLMCredentialCard.tsx`** — displays a single LLM provider credential status
  - Props: `provider`, `credential`, `onConfigure`
  - States: Configured (✓ badge), Not Configured (○ badge)
  - Shows model preview if configured

- **`LLMCredentialModal.tsx`** — form to add/edit LLM credential
  - Props: `provider`, `onSave`, `onClose`
  - Fields: API Key input, Model dropdown, Master Secret input
  - Buttons: Test Connection, Save, Cancel, Delete (if existing)
  - Calls `encryptApiKey()` before submit

- **`RepositoryRow.tsx`** — extended version with provider badge
  - Display provider icon/name (GitHub | GitLab | GitBucket)
  - Show repository info
  - "Launch Workspace" button

### 4.13 Create loading skeletons

- `DashboardSkeleton`, `RepositoriesSkeleton`, `IntegrationsSkeleton`, `WorkspaceSkeleton`, `AdminSettingsSkeleton`
- Use placeholder cards/rows while data loads

### 4.14 Update error codes for integrations

**File:** `frontend/app/lib/auth-errors.ts` (EXTEND)

Add new error code for integration failures:
```ts
export type AuthErrorCode = 
  | "access_denied" 
  | "invalid_state" 
  | "github_unavailable" 
  | "callback_failed"
  | "integration_connection_failed"  // GitLab/GitBucket OAuth failure
  | "unknown";

const AUTH_ERRORS: Record<AuthErrorCode, AuthErrorContent> = {
  // ... existing ...
  integration_connection_failed: {
    code: "integration_connection_failed",
    eyebrow: "INTEGRATION CONNECTION FAILED",
    title: "Could not connect to the integration provider.",
    description: "Check that you approved the authorization request and that the provider is operational.",
    guidance: "Return to integrations and try connecting again."
  },
};
```

### 4.15 Cleanup fixture files

- Delete or archive `frontend/app/lib/dashboard.ts`
- Delete or archive `frontend/app/lib/workspace-fixtures.ts`
- Remove all fixture imports from components
- Verify no mock handlers or fallback fixtures remain

---

## Testing & Verification Checklist

### Backend Tests
- [ ] Start backend: `cd graphify && uv run uvicorn graphify.server.app:app --reload --port 8000`
- [ ] All routes register: check `GET /openapi.json` for new endpoints
- [ ] Test `GET /api/projects` → returns list or empty array
- [ ] Test `GET /api/repositories` → returns list or error if token invalid
- [ ] Test `GET /api/integrations` → returns 3 integrations with status
- [ ] Test `GET /api/integrations/:provider/login` (provider=gitlab|gitbucket) → redirects to provider
- [ ] Test `POST /api/admin/credentials` → encrypts + stores
- [ ] Test `POST /api/admin/credentials/verify` → validates API key
- [ ] Test `DELETE /api/admin/credentials/:provider` → removes credential
- [ ] Run `uv run ruff check graphify/server/` — no errors
- [ ] Run `uv run pyright graphify/server/` — no errors

### Frontend Tests (Local E2E)
- [ ] Start frontend: `cd frontend && npm run dev`
- [ ] Log in via GitHub OAuth at `http://localhost:3000`
- [ ] Verify `/dashboard` loads recent projects or shows empty state
- [ ] Verify `/repositories` loads GitHub repos or shows empty state
- [ ] Verify `/repositories` can search/filter repos
- [ ] Verify `/integrations` loads integration cards
  - [ ] GitHub card shows "Connected" with user login
  - [ ] GitLab card shows "Connect with GitLab" button (if env var set)
  - [ ] GitBucket card shows "Connect with GitBucket" button (if env var set)
- [ ] Test GitLab OAuth flow: click "Connect" → redirected to gitlab.com → approved → token stored
- [ ] Test GitBucket OAuth flow: click "Connect" → redirected to gitbucket → approved → token stored
- [ ] Test disconnect: click "Disconnect" on connected integration → token removed
- [ ] Verify `/admin/settings` (admin-only):
  - [ ] Display OpenAI, Anthropic, Gemini credential cards
  - [ ] Click "Configure" → modal opens
  - [ ] Enter API key + select model → encrypts client-side
  - [ ] Click "Save" → credential stored
  - [ ] Click "Test Connection" → validates key
  - [ ] Click "Delete" → removes credential
- [ ] Verify sidebar navigation works and persists across all screens
- [ ] Verify sidebar is floating inset with 6px border radius
- [ ] Verify sidebar shows user avatar + logout button
- [ ] Verify admin-only routes (403 redirect if user role !== ADMIN)
- [ ] Test mobile view (<768px): sidebar becomes hamburger drawer
- [ ] Click "Launch Workspace" on a repo → navigate to `/projects/:id/launch` or `/workspace/:id`
- [ ] Verify `/workspace/[id]` loads real project data, graph, and files (not fixtures)
- [ ] Test error scenarios:
  - [ ] GitLab/GitBucket env vars not set → show "Not configured" message
  - [ ] OAuth token expired → show "Connection expired, please reconnect"
  - [ ] Invalid LLM API key → "Test Connection" shows error
- [ ] Run `npm run lint` — no errors
- [ ] Run `npm run build` — production build succeeds

### Responsive Design Tests
- [ ] Desktop (1920x1080): sidebar visible, all layouts optimal
- [ ] Tablet (768x1024): layout adjusts, sidebar still visible
- [ ] Mobile (375x812): sidebar hidden, hamburger menu works, drawer slide-out smooth
- [ ] All screens: no horizontal scrolling
- [ ] Touch targets: all buttons ≥48px

### Security & Validation
- [ ] Client-side encryption test: verify key is never sent in plain text
- [ ] Admin credentials test: non-admins cannot access `/admin/settings`
- [ ] Integration state test: connections persist across page refresh
- [ ] Logout test: session cleared, `/api/session` returns 401

---

## Important Notes: Sandbox Isolation & Railway

### Sandbox Architecture (Phase 3 + Phase 4)

The Graphify backend runs on Railway as a FastAPI service. Ephemeral sandboxes for code extraction also run on Railway:

**How it works:**
1. User clicks "Launch Workspace" on a repo
2. Backend creates a Railway ephemeral job:
   - Pulls graphify docker image (Python 3.12 + tree-sitter)
   - Mounts `/workspace` volume for the repository clone
   - Injects env vars: repo URL, active LLM provider key (from `SystemCredential`), project ID
   - Runs: `graphify extract /workspace` (generates graph.json + metadata)
   - Stores outputs to S3/R2 or local storage (configurable)
3. WebSocket stream reports progress (Phase 4)
4. Frontend polls or listens for completion, loads graph + files

**Security & Isolation:**
- Each sandbox runs in an isolated Railway job container
- No container has access to other users' data (Railway manages multi-tenancy)
- Ephemeral volumes are destroyed after job completion
- Credentials (LLM keys) are passed as env vars, encrypted in transit (Railway HTTPS)

**Configuration:**
```env
RAILWAY_API_TOKEN=<railway-api-key>
WORKSPACE_STORAGE_TYPE=s3|local
S3_BUCKET=graphify-workspaces  # if S3
S3_REGION=us-east-1
```

### Phase 3 Scope vs Phase 4

**Phase 3 (this document):**
- Admin LLM credential management (CRUD)
- Integration OAuth flows (GitLab, GitBucket)
- Real data endpoints (projects, repos, integrations)
- Service adapters + UI for all above
- Basic sandbox job creation (no WebSocket/streaming yet)

**Phase 4 (next):**
- WebSocket streaming for real-time provisioning status
- `/ws/projects/:id` for live progress updates (0% → 100%)
- Retry logic + failure recovery
- Launch screen with deterministic phase playback
- Project cancellation mid-provisioning

---

## Blocked dependencies

None. Phase 2 (auth) is complete. Backend database, crypto, session middleware all exist. We can start Phase 3 immediately.

**Prerequisites for this phase:**
- GitLab & GitBucket OAuth apps created (client IDs/secrets known)
- Railway API token available
- Optionally: S3/R2 credentials (if using cloud storage; local storage works for dev)

---

## Follow-up phases

- **Phase 4**: Provisioning WebSocket streaming + launch UX refinement
- **Phase 5**: Token refresh rotation (GitHub/GitLab token expiry handling)
- **Phase 6**: Agent queries, diff inspection, PR dispatch
- **Phase 7**: Sandbox lifecycle & cleanup
- **Phase 8**: PR dispatch automation
- **Phase 9**: System-wide credential management + rate limiting
