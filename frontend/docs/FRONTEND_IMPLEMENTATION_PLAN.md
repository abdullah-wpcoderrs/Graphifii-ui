# Graphify Frontend Implementation Blueprint

**Status:** Ready for approval  
**Frontend host:** Vercel  
**Backend host:** Railway  
**Frontend framework:** Next.js 16 App Router, React 19, TypeScript  
**Primary product:** Graphify Cloud IDE

## What we are building

The frontend is a production-quality web interface for Graphify. It begins
with GitHub App authentication, continues into repository discovery and
workspace provisioning, and culminates in a three-pane cloud IDE containing a
Monaco code editor, an interactive Graphify architecture graph, and a
graph-aware AI agent.

The frontend is a client of the Railway-hosted Graphify backend. It does not
own authentication secrets, GitHub credentials, database access, sandbox
orchestration, AI-provider credentials, repository mutation, or pull request
creation logic.

## Language we agreed on

- **Dashboard:** The authenticated repository-management surface where users
  discover repositories and launch or resume projects.
- **Workspace:** The persistent product representation of a repository,
  including graph artifacts, branch state, modified files, and IDE state.
- **Sandbox:** Temporary backend compute attached to a workspace for cloning,
  extraction, agent operations, and Git operations.
- **Graph-aware agent:** An AI coding agent grounded in Graphify's structural
  graph and whose proposed changes remain reviewable before PR creation.
- **Centralized credentials:** Administrator-managed provider credentials that
  are never exposed to regular users or shipped in the frontend bundle.

## Decisions made

- Vercel owns the Next.js frontend deployment.
- Railway owns the complete Python/FastAPI backend.
- The root route `/` is the GitHub authentication screen, not a marketing page.
- GitHub App authorization and installation are used instead of a traditional
  broad-scope OAuth App.
- GitHub authentication callbacks, tokens, and installation state belong to
  the Railway backend.
- The frontend has one public environment variable:
  `NEXT_PUBLIC_API_URL`.
- API payloads are represented by validated TypeScript contracts.
- UI development starts against realistic mock implementations of those
  contracts and switches to Railway without rewriting screen components.
- Main structural surfaces use sharp corners; rounding is reserved for
  controls, badges, and the agent composer.
- The workspace is desktop-first. Below the full three-pane breakpoint,
  panels become selectable views instead of being compressed into unusable
  widths.

## Assumptions

- Production will use same-site custom domains such as `app.example.com` and
  `api.example.com`. This is strongly preferred for reliable secure-cookie
  authentication. Localhost works across ports with credentialed CORS.
- Until the backend endpoints exist, mocked contracts are the frontend's
  source of runtime data.
- The initial user role comes from the backend session response. The frontend
  does not decide who is an administrator.
- Graph nodes contain enough source-location metadata to focus Monaco on a
  file and line.
- Agent modifications arrive as proposals and are never silently committed.
- A workspace can be restored after its sandbox has been terminated.
- The first release is English-only and dark-theme-only.

## Non-goals for the frontend

- Storing GitHub, database, LLM, or encryption secrets
- Running Graphify extraction in the browser
- Direct browser-to-GitHub privileged API calls
- Implementing a second backend in Next.js route handlers
- Managing containers, queues, object storage, or database migrations
- A mobile code-editing experience equivalent to desktop
- Billing, marketplace distribution, or organization member management in the
  initial UI release

## Screen and route map

| Route | Access | Screen | Primary responsibility |
| --- | --- | --- | --- |
| `/` | Public | Authentication | Explain Graphify briefly and start GitHub authorization |
| `/auth/error` | Public | Authentication error | Recover from denial, invalid state, callback, or server errors |
| `/onboarding/github` | Authenticated | GitHub App setup | Install the app or repair missing repository access |
| `/dashboard` | Authenticated | Repository dashboard | Search, filter, launch, and resume repositories |
| `/projects/[projectId]/launch` | Authenticated | Workspace provisioning | Show clone, dependency, extraction, and graph-build progress |
| `/workspace/[projectId]` | Authenticated | Graphify IDE | Editor, architecture graph, AI agent, diffs, and PR action |
| `/admin/credentials` | Admin | AI credentials | Configure and verify centralized provider credentials |
| `/settings/integrations` | Authenticated | GitHub integration | View installation state and change repository access |
| `/forbidden` | Authenticated | Permission error | Explain an unavailable admin or repository action |
| `not-found` | Any | Not found | Recover to dashboard or authentication |

## Global visual system

### Tokens

- App canvas: `#09090B`
- Panel surface: `#121215`
- Editor surface: `#0D0D10`
- Input surface: `#18181B`
- Structural border: `#27272A`
- Focus border: `#3F3F46`
- Primary action: `#10B981`
- Active selection: `#3B82F6`
- God-node accent: `#8B5CF6`
- Primary text: `#FFFFFF`
- Secondary text: `#A1A1AA`
- Muted text: `#52525B`

### Geometry

- Structural panel radius: `0`
- Controls and buttons: `4px` to `6px`
- Status pills: `14px` to `16px`
- Workspace header height: `44px`
- Structural borders: `1px`
- Workspace default widths: editor `35%`, graph `40%`, agent `25%`

### Typography

- UI: Geist/Inter-compatible sans serif
- Code and technical state: Geist Mono/JetBrains Mono-compatible monospace
- Default UI copy: `13px`
- Header repository title: `14px`, semibold
- Editor: `14px` with `21px` line height

### Accessibility baseline

- Every interactive element is keyboard reachable.
- Visible focus treatment is never removed.
- Icon-only buttons have accessible names and tooltips.
- Color is not the only status indicator.
- Text and controls meet WCAG AA contrast.
- Reduced-motion preferences disable non-essential animation.
- Loading regions expose status through appropriate ARIA semantics.

## Screen specifications

### 1. Authentication screen — `/`

#### Content

- Graphify mark and product name
- Concise value proposition: understand, modify, and ship code with a
  graph-aware cloud workspace
- Primary **Continue with GitHub** action
- Brief permission explanation
- Links to privacy and terms placeholders only if corresponding pages exist
- Subtle architecture-graph visual treatment; no marketing-site navigation

#### States

- Ready
- Checking an existing session
- Redirecting to GitHub
- Backend unavailable
- Existing authenticated session: redirect to `/dashboard`

#### Acceptance criteria

- No secret or GitHub client identifier is present in the client bundle.
- The button navigates to
  `${NEXT_PUBLIC_API_URL}/api/auth/github/login`.
- Authentication failures provide a retry and a plain-language explanation.
- The screen works at mobile, tablet, and desktop widths.

### 2. Authentication error — `/auth/error`

#### Content and states

- User denied authorization
- Expired or invalid OAuth state
- GitHub App unavailable
- Backend callback failure
- Generic fallback with safe correlation ID

#### Actions

- Retry authentication
- Return to `/`
- Never render raw backend traces or token details

### 3. GitHub onboarding — `/onboarding/github`

#### Content

- Signed-in GitHub identity
- GitHub App installation status
- Explanation of selected-repository access
- **Install Graphify GitHub App** or **Configure repository access**
- Confirmation after installation

#### States

- User authorized, app not installed
- Installed with no repositories
- Installed with selected repositories
- Organization approval pending
- Installation suspended or removed

### 4. Repository dashboard — `/dashboard`

#### Layout

- Compact application header with Graphify identity, sync status, admin link
  when permitted, and user menu
- Page heading and repository count
- Search input
- Ownership filter: all, personal, organizations
- State filter: available, provisioning, ready, failed
- Repository cards or dense rows

#### Repository item

- Owner/repository
- Private/public state
- Default branch
- Language
- Last push time
- Graphify project state
- Last indexed time when available
- Primary action: **Launch Workspace**, **Resume Workspace**, or **Retry**

#### States

- Initial loading skeleton
- Repository list
- No GitHub installation
- Installation has no selected repositories
- No search results
- Repository sync in progress
- Backend error with retry
- Rate-limited response

### 5. Workspace provisioning — `/projects/[projectId]/launch`

#### Progress phases

1. Creating sandbox
2. Cloning repository
3. Detecting languages
4. Parsing source files
5. Building relationships and communities
6. Persisting graph artifacts
7. Preparing workspace

#### UI

- Repository and branch identity
- Overall progress bar and numerical percentage
- Current phase
- Compact event log
- Elapsed time
- Cancel or return-to-dashboard action when supported
- Automatic redirect to the workspace at `READY`

#### Failure handling

- Human-readable phase failure
- Safe backend error identifier
- Retry action
- Return to dashboard
- Never imply that partial progress was persisted unless confirmed

### 6. Graphify workspace — `/workspace/[projectId]`

#### Header

- Owner/repository
- Active branch selector
- Extraction/WebSocket state
- Changed-files count
- Admin settings shortcut for admins
- **Create Pull Request** primary action

#### Left panel: editor

- File explorer
- Open-file tabs
- Monaco editor
- Source location navigation
- Modified-file indicators
- Editor/diff mode selector
- Inline or side-by-side Monaco diff
- Loading, binary-file, missing-file, and oversized-file states

#### Center panel: graph

- React Flow canvas
- Zoom and fit controls
- Search
- Node-type filters
- Community filter
- Edge visibility controls
- Standard nodes
- Purple high-centrality/god nodes
- Blue selected state
- Node detail drawer or inspector
- Empty, loading, malformed-graph, and large-graph states

#### Right panel: agent

- **Agent** and **Output Log** tabs
- Conversation history
- Streaming/working state
- Prompt composer
- Stop-generation action
- Suggested graph queries when empty
- Tool/activity entries
- Proposed-file-change summary
- **Inspect Diff** action
- **Prepare Pull Request** action
- Error, reconnecting, and provider-unavailable states

#### Cross-panel behavior

- Selecting a graph node opens its source file and focuses the relevant line.
- Selecting a file highlights matching graph nodes when mappings exist.
- Selecting a proposed change opens the corresponding Monaco diff.
- Workspace route state preserves selected file, graph node, and right-panel tab
  where practical.
- Panel resizing respects documented minimum and maximum bounds.

#### Narrow viewport behavior

- At widths too narrow for three panes, show one active workspace panel at a
  time using Editor, Graph, and Agent tabs.
- Keep repository identity and extraction state visible.
- Do not attempt a full mobile Monaco editing experience.

### 7. Admin credentials — `/admin/credentials`

#### Content

- Provider cards for OpenAI, Anthropic, and Gemini
- Configured/not-configured state
- Last-updated metadata
- Masked key input
- Save, replace, verify, and remove actions
- Explanation that credentials are organization-level

#### Security behavior

- Never fetch or reveal an existing plaintext key.
- Never persist plaintext values in browser storage.
- Clear sensitive inputs after submission or navigation.
- Use Web Crypto through a dedicated client-only utility when the backend
  encryption contract is finalized.
- Destructive removal requires explicit confirmation.

#### Authorization states

- Admin
- Non-admin redirect to `/forbidden`
- Session expired
- Provider verification failure

### 8. Integration settings — `/settings/integrations`

- GitHub identity
- Installation owner
- Selected repository count
- Installation health
- Configure repository access
- Reauthorize
- Disconnect with explicit warning

## Frontend architecture

### Proposed source layout

```text
frontend/
├── app/
│   ├── (public)/
│   │   ├── page.tsx
│   │   └── auth/error/page.tsx
│   ├── (authenticated)/
│   │   ├── layout.tsx
│   │   ├── dashboard/page.tsx
│   │   ├── onboarding/github/page.tsx
│   │   ├── projects/[projectId]/launch/page.tsx
│   │   ├── workspace/[projectId]/page.tsx
│   │   ├── settings/integrations/page.tsx
│   │   └── admin/credentials/page.tsx
│   ├── forbidden/page.tsx
│   ├── error.tsx
│   ├── not-found.tsx
│   ├── layout.tsx
│   └── globals.css
├── components/
│   ├── auth/
│   ├── dashboard/
│   ├── workspace/
│   │   ├── editor/
│   │   ├── graph/
│   │   └── agent/
│   ├── admin/
│   ├── shell/
│   └── ui/
├── lib/
│   ├── api/
│   ├── contracts/
│   ├── env/
│   ├── mocks/
│   └── utils/
├── hooks/
├── providers/
└── tests/
```

### Rendering boundaries

- Pages and layouts remain Server Components by default.
- Browser-only libraries such as Monaco, React Flow, Web Crypto, and
  WebSockets are isolated behind small Client Component boundaries.
- Browser-only heavy components are dynamically imported.
- Authentication truth comes from the backend session endpoint.
- No GitHub or Graphify business logic is duplicated in Next.js route
  handlers.

### State ownership

- URL state: project ID, selected file where shareable, filters where useful
- Remote state: session, repositories, projects, graph metadata, credentials
- Workspace UI state: panel sizes, active file, selected graph node, active tab
- Ephemeral component state: menus, dialogs, draft prompts
- Secrets: never stored in global state, URL state, or local storage

Use component state first. Add a small workspace store only when cross-panel
coordination requires it; do not introduce a global state library for simple
page-local state.

## Frontend API contract

The initial frontend service layer should expose typed operations equivalent to:

```text
GET    /api/session
POST   /api/auth/logout
GET    /api/github/installations
GET    /api/github/repositories
POST   /api/github/repositories/sync
GET    /api/projects
POST   /api/projects
GET    /api/projects/{projectId}
GET    /api/projects/{projectId}/files
GET    /api/projects/{projectId}/files/content
GET    /api/projects/{projectId}/graph
GET    /api/projects/{projectId}/changes
POST   /api/projects/{projectId}/agent/messages
POST   /api/projects/{projectId}/pull-requests
GET    /api/admin/credentials
PUT    /api/admin/credentials/{provider}
DELETE /api/admin/credentials/{provider}
POST   /api/admin/credentials/{provider}/verify
WS     /ws/projects/{projectId}
```

The WebSocket transports lifecycle events such as:

```text
workspace.provisioning
workspace.ready
workspace.failed
graph.indexing.progress
graph.updated
file.changed
agent.status
agent.message.delta
agent.message.completed
agent.failed
pull_request.created
```

Every response contract should be runtime-validated at the API boundary. UI
components receive parsed domain objects rather than unchecked JSON.

## Core frontend domain types

- `Session`
- `SessionUser`
- `UserRole`
- `GitHubInstallation`
- `RepositorySummary`
- `Project`
- `ProjectStatus`
- `ProvisioningProgress`
- `WorkspaceFile`
- `FileContent`
- `GraphDocument`
- `GraphNode`
- `GraphEdge`
- `GraphCommunity`
- `SourceLocation`
- `FileChange`
- `DiffProposal`
- `AgentMessage`
- `AgentActivity`
- `CredentialProviderStatus`
- `ApiError`

## Dependency policy

Add a dependency only when it owns a difficult, well-defined responsibility.
The expected initial set is:

- `@monaco-editor/react` for editing and diff inspection
- `@xyflow/react` for the architecture graph
- `react-resizable-panels` for accessible workspace resizing
- `zod` for environment and API contract validation
- `lucide-react` for a consistent icon set

Before installation, verify current compatibility with Next.js 16 and React 19.
Do not introduce a component framework, animation framework, form framework,
global state library, or server-state library until complexity demonstrates a
need.

## Environment contract

The frontend contains only:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Rules:

- Validate the value once at application startup.
- Remove trailing slashes before composing API paths.
- Derive `ws://` or `wss://` from the API URL; do not add a second WebSocket
  environment variable.
- Never add GitHub credentials or provider keys to Vercel.
- Use preview-specific API URLs for Vercel preview environments when a
  corresponding backend environment exists.

## Implementation phases and task checklist

### Phase 0 — Confirm the blueprint

- [ ] Review this plan.
- [ ] Confirm the screen map and implementation order.
- [ ] Confirm same-site production domains or select a token-based alternative.
- [ ] Confirm the desktop-first/narrow-panel workspace behavior.
- [ ] Confirm contract-first mocked UI development.

### Phase 1 — Frontend foundation

- [ ] Read the bundled Next.js 16 documentation relevant to App Router,
  environment variables, authentication boundaries, client components, error
  handling, and deployment.
- [ ] Replace generated metadata with Graphify metadata.
- [ ] Establish route groups for public and authenticated screens.
- [ ] Implement design tokens in `globals.css`.
- [ ] Establish typography, reset, focus, scrollbar, and selection styles.
- [ ] Build primitive Button, IconButton, Input, Select, Badge, Spinner,
  Skeleton, Tooltip, EmptyState, ErrorState, and Dialog components.
- [ ] Add the validated public environment reader.
- [ ] Add the typed API client with credentialed requests.
- [ ] Add normalized API error handling.
- [ ] Add mock and HTTP implementations behind one service interface.
- [ ] Create fixtures for user, installation, repositories, projects, graph,
  files, diffs, agent messages, and credentials.
- [ ] Implement global error and not-found screens.
- [ ] Verify lint, type checking, and production build.

### Phase 2 — Authentication UI

- [ ] Build the `/` authentication screen.
- [ ] Build session-checking and authenticated redirect behavior.
- [ ] Connect **Continue with GitHub** to the backend login URL.
- [ ] Prevent duplicate redirect clicks.
- [ ] Build `/auth/error` with safe error mapping.
- [ ] Add backend-unavailable recovery.
- [ ] Add responsive and keyboard states.
- [ ] Test ready, loading, redirecting, error, and existing-session cases.
- [ ] Verify no backend secret appears in the built client assets.

### Phase 3 — GitHub onboarding and protected shell

- [ ] Build the authenticated application shell.
- [ ] Build user menu and logout.
- [ ] Build role-aware navigation without treating hidden UI as authorization.
- [ ] Build `/onboarding/github`.
- [ ] Build installation-required, no-repositories, pending-approval, suspended,
  and connected states.
- [ ] Wire install/configure actions to backend-generated GitHub URLs.
- [ ] Build `/settings/integrations`.
- [ ] Add expired-session handling.

### Phase 4 — Repository dashboard

- [x] Build dashboard header and repository summary.
- [x] Build search and filters.
- [x] Build repository card/dense-row component.
- [x] Build launch, resume, retry, and unavailable actions.
- [x] Build loading skeleton.
- [x] Build empty-installation and no-selected-repositories states.
- [x] Build no-results, sync, rate-limit, and generic error states.
- [x] Preserve useful filters in the URL.
- [x] Verify dashboard responsiveness and keyboard navigation.

### Phase 5 — Project launch and indexing

- [x] Build `/projects/[projectId]/launch`.
- [x] Define progress phase presentation.
- [x] Build progress bar, percentage, phase label, and event log.
- [x] Implement mock WebSocket event playback.
- [ ] Implement real WebSocket client with reconnect and cleanup.
- [x] Handle out-of-order, repeated, and terminal events safely.
- [x] Redirect to the workspace only on a confirmed ready event.
- [x] Build failure and retry states.
- [x] Build return-to-dashboard behavior.

### Phase 6 — Workspace shell

- [x] Build the fixed 44px workspace header.
- [x] Build repository identity and branch selector.
- [x] Build connection/indexing indicator.
- [x] Build changed-file count and Create PR action.
- [x] Build three resizable panels with documented bounds.
- [x] Persist panel dimensions locally without persisting secrets.
- [x] Build narrow-width panel tabs.
- [ ] Add workspace-level loading, disconnected, failed, and restored states.
- [x] Establish the cross-panel selection model.

### Phase 7 — Monaco editor and diff

- [x] Install and dynamically load Monaco.
- [x] Apply the documented editor configuration.
- [x] Build file explorer and expandable folders.
- [x] Build open-file tabs.
- [ ] Fetch and render file content by source path.
- [x] Handle source-location focus from graph selection.
- [x] Show modified-file markers.
- [ ] Build inline and side-by-side diff inspection.
- [ ] Handle deleted, renamed, new, binary, oversized, and unavailable files.
- [ ] Add editor loading and failure states.
- [x] Verify keyboard behavior and resize handling.

### Phase 8 — Interactive Graphify graph

- [x] Install and dynamically load React Flow.
- [x] Add Graphify-to-React-Flow data adapter.
- [x] Build standard, selected, and god-node visuals.
- [x] Build edge styling and arrow direction where graph data provides it.
- [x] Build zoom, fit, and reset controls.
- [x] Build graph search.
- [x] Build node-type and community filters.
- [x] Build node detail inspector.
- [x] Connect node selection to Monaco source focus.
- [x] Connect file selection to graph highlighting.
- [ ] Handle empty, invalid, stale, loading, and large graphs.
- [ ] Add performance safeguards for high node counts.

### Phase 9 — Agent and output log

- [x] Build Agent/Output Log tabs.
- [x] Build empty-state query suggestions.
- [x] Build message list and semantic message roles.
- [x] Build prompt composer and send behavior.
- [x] Build streaming message updates.
- [x] Build stop-generation behavior.
- [ ] Build tool/activity timeline.
- [ ] Build output log filtering and auto-scroll controls.
- [x] Build proposed-change summary.
- [x] Connect **Inspect Diff** to Monaco.
- [ ] Connect **Prepare Pull Request** to the PR review flow.
- [ ] Handle reconnecting, canceled, provider-error, and agent-error states.

### Phase 10 — Pull request workflow

- [ ] Build changed-files review dialog or drawer.
- [ ] Build PR title and description form.
- [ ] Show base and head branches.
- [ ] Show validation and branch-conflict errors.
- [ ] Require explicit confirmation before dispatch.
- [ ] Disable duplicate submissions.
- [ ] Show creation progress.
- [ ] Show created PR number and GitHub link.
- [ ] Preserve the workspace if PR creation fails.

### Phase 11 — Admin credentials

- [ ] Build admin route guard behavior based on backend session role.
- [ ] Build provider status cards.
- [ ] Build masked credential entry and replacement flow.
- [ ] Build verification status and errors.
- [ ] Build removal confirmation.
- [ ] Clear plaintext input after submission.
- [ ] Implement Web Crypto only after agreeing on the backend encryption
  envelope and public-key/key-derivation model.
- [ ] Verify non-admin and expired-session states.
- [ ] Verify no plaintext credential reaches logs or browser storage.

### Phase 12 — Quality and deployment readiness

- [ ] Add unit tests for contract parsers, API errors, URL builders, graph
  adapters, and workspace reducers/store.
- [ ] Add component tests for critical screen states.
- [ ] Add end-to-end tests for authentication redirect, onboarding, repository
  launch, progress, cross-panel navigation, diff inspection, and PR review.
- [ ] Audit keyboard navigation.
- [ ] Audit WCAG AA contrast.
- [ ] Test reduced motion.
- [ ] Test supported browsers.
- [ ] Verify loading and error boundaries.
- [ ] Verify WebSocket teardown and reconnection.
- [ ] Verify no secrets occur in client bundles or browser storage.
- [ ] Run lint.
- [ ] Run type checking.
- [ ] Run tests.
- [ ] Run a clean production build.
- [ ] Test Vercel preview deployment against a safe backend environment.
- [ ] Configure production `NEXT_PUBLIC_API_URL`.
- [ ] Verify Railway CORS allowlist and cookie policy.
- [ ] Verify custom app/API domains and HTTPS.

## Milestone order

### Milestone 1 — Auth foundation

Phases 1 and 2. Delivers the visual system, typed service boundary, mock
infrastructure, and the complete authentication landing experience.

### Milestone 2 — Repository journey

Phases 3 through 5. Delivers GitHub onboarding, dashboard, repository launch,
and real-time provisioning states.

### Milestone 3 — Core IDE

Phases 6 through 8. Delivers the resizable workspace, Monaco editing/diff
experience, React Flow graph, and bidirectional navigation.

### Milestone 4 — Agent-to-PR journey

Phases 9 and 10. Delivers agent interaction, proposed changes, diff inspection,
and PR preparation.

### Milestone 5 — Administration and hardening

Phases 11 and 12. Delivers centralized credential management, comprehensive
testing, accessibility, and production readiness.

## Definition of done

The frontend is complete when:

- A user can authenticate through the GitHub App flow.
- A user can install/configure the app and see permitted repositories.
- A user can launch a repository and observe accurate provisioning progress.
- A ready workspace renders source, graph, and agent panels.
- Graph and editor selection work bidirectionally.
- Agent changes are inspectable in Monaco before dispatch.
- A user can prepare and create a PR through the backend.
- An admin can configure provider credentials without exposing existing
  plaintext values.
- All material loading, empty, error, reconnecting, and permission states are
  intentionally designed.
- The application passes lint, type checks, automated tests, accessibility
  checks, and a clean production build.
- The Vercel bundle contains no backend secrets.

## First execution slice after approval

1. Read the relevant bundled Next.js 16 documentation.
2. Install only the Phase 1 dependencies that are immediately required.
3. Replace the generated metadata and default page.
4. Establish Graphify design tokens and UI primitives.
5. Implement the typed environment and API boundary.
6. Implement mock session states.
7. Build and verify the authentication screen and authentication error screen.
8. Stop for visual review before beginning the repository dashboard.
