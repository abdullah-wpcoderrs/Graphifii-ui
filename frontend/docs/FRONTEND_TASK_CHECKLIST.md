# Graphify frontend task checklist

Last updated: 2026-07-31

**Note (2026-07-31):** Remaining open items below are reconciled against
`IMPLEMENTATION_PLAN.md` / `TASK_CHECKLIST.md` (Phase 3). Items already fully
scoped there are marked accordingly instead of duplicated. Two items were
superseded by a later decision (no mock-data fallback — fixtures are being
deleted outright, not extended with an HTTP/mock adapter split).

## Authentication screen

- [x] Capture the Kodus sign-up desktop layout.
- [x] Capture the source mobile behavior.
- [x] Record the looping auth-screen motion and form states.
- [x] Apply Graphify color, type, geometry, and focus tokens.
- [x] Build the responsive `/` authentication screen.
- [x] Add the animated repository-to-graph workspace preview.
- [x] Add reduced-motion behavior.
- [x] Connect the primary action to
  `${NEXT_PUBLIC_API_URL}/api/auth/github/login`.
- [x] Prevent duplicate redirect clicks.
- [x] Add a safe missing-API-configuration recovery state.
- [x] Add the backend session check and authenticated `/dashboard` redirect.
  `AuthScreen` calls `GET /api/session` on mount; a valid session
  `router.replace("/dashboard")`s before the GitHub button renders, a 401
  falls through to the normal sign-in form, and any other failure
  (network/config) also falls through rather than blocking sign-in. Verified
  in-browser against the live local backend (401 → sign-in form shown, no
  console errors).
- [x] Build `/auth/error` with safe error-code mapping.
- [ ] Test against the live Railway authentication service. **Blocked** — no
  Railway deploy exists yet; this needs a live URL, not local dev. Revisit at
  deploy time.

## Frontend foundation

- [x] Replace generated metadata with Graphify metadata.
- [x] Establish the documented Graphify visual tokens.
- [x] Add a validated public API URL reader.
- [x] Extract shared Button, Input, Badge, Spinner, and ErrorState primitives.
  Added at `app/components/ui/` (`button.tsx`, `input.tsx`, `badge.tsx`,
  `spinner.tsx`, `error-state.tsx`) plus `app/components/empty-state.tsx`,
  styled via new `.ui-*` classes in `globals.css` generalized from the
  existing `.github-button` / `.repository-state-badge` / `.auth-error`
  patterns. Existing screens' one-off classes were left untouched (no
  regression risk); Phase 3 screens will consume these primitives directly.
- [x] Add the credentialed typed API client.
  `app/lib/api-client.ts` — `apiFetch`/`apiGet`/`apiPost`/`apiPut`/`apiDelete`,
  always sends `credentials: "include"`, JSON-encodes bodies.
- [x] Add normalized frontend API errors.
  `app/lib/api-errors.ts` — `ApiError` (with `.status`/`.code`/
  `.isUnauthorized`/`.isForbidden`/`.isNotFound`), `ApiConfigError`,
  `ApiNetworkError`. `app/lib/session.ts` built on top as the first consumer
  (`fetchSession`, `logout`).
- [x] ~~Add mock and HTTP service adapters~~ — **superseded.** Per the
  no-fixtures decision, only the real HTTP adapter is being built; there is
  no mock-mode branch to add.
- [x] ~~Create contract fixtures for the remaining product screens~~ —
  **superseded**, same reason. Existing fixtures (`dashboard.ts`,
  `workspace-fixtures.ts`) are being deleted, not extended — see Phase 3
  `TASK_CHECKLIST.md` → Cleanup.
- [x] Build global error and not-found screens.

## Next screens

- [x] GitHub App onboarding and repository-access repair.
- [x] Repository dashboard with search, filters, and launch/resume actions.
- [x] Workspace provisioning and extraction progress.
- [x] Three-pane Graphify workspace shell.
- [x] Monaco editor and diff inspection.
- [x] Interactive architecture graph.
- [x] Graph-aware agent and output log.
- [ ] Pull request preparation and dispatch. **Deferred** — Phase 6, not part
  of this build.
- [ ] Admin provider-credentials screen. **Scoped into Phase 3** —
  `IMPLEMENTATION_PLAN.md` §4.7, `TASK_CHECKLIST.md` → "Admin Settings
  Screen". Not duplicating here.
- [ ] Integration settings and permission states. **Scoped into Phase 3** —
  `IMPLEMENTATION_PLAN.md` §4.6, `TASK_CHECKLIST.md` → "Integrations Screen
  (Enhanced)". Not duplicating here.

## Backend integration cleanup

All six items below are **scoped into Phase 3** (`IMPLEMENTATION_PLAN.md` /
`TASK_CHECKLIST.md`) rather than tracked separately here, since they're the
same work as "replace fixtures with real data" for the dashboard/repositories/
integrations screens:

- [ ] Replace frontend mock service adapters and fixture-backed responses with
  the implemented backend HTTP and WebSocket API routes. → Phase 3 §4.9, 4.15.
- [ ] Remove temporary mock API routes after every consumer has been migrated
  to the corresponding backend route. → Phase 3 Cleanup section.
- [ ] Replace the GitHub onboarding `state` query-parameter simulator with live
  GitHub App installation and repository-access state. → Phase 3 Integrations
  routes (`GET /api/integrations`).
- [ ] Connect GitHub App install, approval, repair, suspension, removal, and
  repository-selection actions to the implemented backend routes. → Phase 3
  Integrations routes.
- [ ] Remove GitHub App mock identities, organizations, repository counts, and
  installation fixtures once live session data is available. → Phase 3
  Cleanup section.
- [ ] Confirm no mock-only route, fixture, query parameter, or fallback can be
  reached in the production build. → Phase 3 Testing & Verification checklist.

## Quality gates

- [x] Run lint.
- [x] Run TypeScript validation.
- [x] Run a production build.
- [x] Verify desktop, tablet, and mobile layouts in-browser.
- [x] Verify keyboard, focus, redirecting, error, and reduced-motion states.
- [ ] Confirm the production client bundle contains no backend secret.
  Deferred until Phase 3 introduces the first thing that could plausibly leak
  one (admin LLM credential handling, client-side encryption) — re-check the
  built bundle at that point.
