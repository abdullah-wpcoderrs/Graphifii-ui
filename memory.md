# Memory — Graphify Authentication, Dashboard, Provisioning, and Workspace UI

Last updated: 2026-07-31 03:08 WAT

## What was built

- Replaced the generated frontend landing page with a responsive Graphify
  GitHub authentication screen at `/`, including a reduced-motion-aware
  repository-to-graph preview and safe missing-configuration state.
- Added the branded authentication error route at `/auth/error`, with
  allow-listed error-code mapping and sanitized safe references.
- Added the GitHub App onboarding route at `/onboarding/github`, covering
  not-installed, no-repositories, connected, approval-pending, suspended, and
  removed installation states.
- Added the repository dashboard at `/dashboard`, with a responsive dense-row
  and card layout, URL-backed search and filters, typed repository fixtures,
  and launch, resume, retry, and provisioning actions.
- Added dashboard loading, syncing, no-installation, no-selected-repositories,
  no-results, rate-limit, and backend-error states.
- Added contract-first workspace provisioning at
  `/projects/[projectId]/launch`, including deterministic phase playback,
  progress/event reporting, failure and retry recovery, and ready-state
  handoff.
- Added the three-pane workspace at `/workspace/[projectId]`, with dynamically
  loaded Monaco source/diff editors, an interactive React Flow architecture
  graph, a graph-aware agent, proposed-change review, and an output log.
- Added resizable desktop panes with local non-sensitive width persistence and
  one-pane responsive Editor/Graph/Agent tabs at narrower breakpoints.
- Refined the file explorer into a VS Code-style expandable tree with
  recognizable folder, Python, Markdown, and fallback file icons.
- Added the shared recovery composition used by authentication errors and the
  application 404 screen.
- Added the root Next.js global 500 boundary with retry and return actions.
- Added shared brand assets and components, Graphify UI tokens and responsive
  styles, a frontend task checklist, browser QA notes, and `ui-registry.md`.

## Decisions made

- The authentication screen follows the observed Kodus split-screen layout and
  motion model while using Graphify colors, typography, sharp panels, and
  emerald actions.
- Authentication errors are selected from a local allow-list. Raw provider or
  backend errors are never rendered in the browser.
- The GitHub onboarding UI is contract-first. Until backend endpoints exist,
  typed visual states are selected with the `state` query parameter rather
  than guessed API calls.
- Shared recovery screens use one branded composition. The global error
  boundary mirrors it with inline style tokens because it replaces the root
  layout and global stylesheet.
- GitHub permissions are explained before the primary installation action, and
  identity, installation, and repository access remain separate checklist
  steps.
- Repository collections use dense rows on desktop and stacked cards below
  `860px`, preserving scanability and the PRD's card requirement.
- Dashboard fixtures remain contract-first and are isolated in
  `app/lib/dashboard.ts` for later replacement by a service adapter.
- Provisioning and workspace fixtures are isolated in
  `app/lib/workspace-fixtures.ts`; the components consume those contracts
  without inventing backend request shapes.
- Monaco and React Flow are dynamically loaded client modules so the heavy
  workspace dependencies do not enter unrelated route bundles.
- Graph selection and source selection share one state model: choosing a node
  opens its source file and line, while the selected file highlights matching
  graph context.
- Workspace pane widths are stored in browser local storage because they are
  presentation preferences, not server or credential data.

## Problems solved

- Updated the implementation for Next.js 16 conventions: page search
  parameters are awaited, and the global error boundary uses
  `unstable_retry`, includes its own document shell, and does not depend on
  root styles.
- Confirmed that unsafe authentication reference values are discarded.
- Confirmed the global 500 boundary with a temporary throwing route, then
  removed that route after browser verification.
- Verified that all onboarding states remain free of horizontal overflow on
  mobile and that unknown routes render the Graphify 404 screen.
- Confirmed dashboard filters persist in the URL and the dashboard remains free
  of horizontal overflow at desktop, tablet, and mobile widths.
- Confirmed provisioning reaches ready once, redirects into the workspace, and
  exposes a stable retry path for the fixture failure state.
- Confirmed Monaco, React Flow, graph-to-editor navigation, diff inspection,
  pane resizing, agent responses, output filtering, and responsive workspace
  tabs work in the browser.
- Confirmed explorer folders collapse/reopen and file selection synchronizes
  the file row, file-type icon, editor tab, and Monaco document.

## Current state

- `/`, `/auth/error`, `/onboarding/github`, `/dashboard`,
  `/projects/[projectId]/launch`, `/workspace/[projectId]`, the global 500
  boundary, and the 404 screen are implemented.
- ESLint, TypeScript validation, `git diff --check`, and the Next.js production
  build pass.
- Browser QA passed for desktop and mobile layouts, all six onboarding states,
  dashboard list/filter/sync/no-results/error states, unsafe auth references,
  unknown routes, and the controlled 500 failure.
- The local development server is available at `http://localhost:3000`; the
  workspace is currently open in the in-app browser.
- The UI remains contract-first. Live session checks, GitHub App installation
  calls, repository data, and backend authentication services are not wired.
- Provisioning still uses deterministic fixture playback rather than the real
  reconnecting WebSocket. Workspace source, graph, agent, and log data are
  fixture-backed rather than connected to backend APIs.
- The worktree contains the current frontend implementation plus earlier
  uncommitted setup/documentation changes. Preserve unrelated changes.

## Next session starts with

1. Run `/remember restore` and confirm this state.
2. Build pull request preparation and dispatch from the reviewed workspace
   changes.
3. Keep the PR flow contract-first until the backend endpoints and GitHub
   mutation contract are confirmed.
4. Add the real provisioning WebSocket and workspace service adapters when the
   backend contracts are available.
5. Run the Imprint and Review skills, then repeat lint, TypeScript, production
   build, and responsive browser QA.

## Open questions

- Confirm the exact backend endpoint or GitHub installation URL used by the
  onboarding primary action when backend integration begins.
- Confirm the production session-cookie domain strategy before wiring the live
  Railway authentication service.
