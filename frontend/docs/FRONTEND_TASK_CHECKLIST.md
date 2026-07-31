# Graphify frontend task checklist

Last updated: 2026-07-31

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
- [ ] Add the backend session check and authenticated `/dashboard` redirect.
- [x] Build `/auth/error` with safe error-code mapping.
- [ ] Test against the live Railway authentication service.

## Frontend foundation

- [x] Replace generated metadata with Graphify metadata.
- [x] Establish the documented Graphify visual tokens.
- [x] Add a validated public API URL reader.
- [ ] Extract shared Button, Input, Badge, Spinner, and ErrorState primitives.
- [ ] Add the credentialed typed API client.
- [ ] Add normalized frontend API errors.
- [ ] Add mock and HTTP service adapters.
- [ ] Create contract fixtures for the remaining product screens.
- [x] Build global error and not-found screens.

## Next screens

- [x] GitHub App onboarding and repository-access repair.
- [x] Repository dashboard with search, filters, and launch/resume actions.
- [x] Workspace provisioning and extraction progress.
- [x] Three-pane Graphify workspace shell.
- [x] Monaco editor and diff inspection.
- [x] Interactive architecture graph.
- [x] Graph-aware agent and output log.
- [ ] Pull request preparation and dispatch.
- [ ] Admin provider-credentials screen.
- [ ] Integration settings and permission states.

## Backend integration cleanup

- [ ] Replace frontend mock service adapters and fixture-backed responses with
  the implemented backend HTTP and WebSocket API routes.
- [ ] Remove temporary mock API routes after every consumer has been migrated
  to the corresponding backend route.
- [ ] Replace the GitHub onboarding `state` query-parameter simulator with live
  GitHub App installation and repository-access state.
- [ ] Connect GitHub App install, approval, repair, suspension, removal, and
  repository-selection actions to the implemented backend routes.
- [ ] Remove GitHub App mock identities, organizations, repository counts, and
  installation fixtures once live session data is available.
- [ ] Confirm no mock-only route, fixture, query parameter, or fallback can be
  reached in the production build.

## Quality gates

- [x] Run lint.
- [x] Run TypeScript validation.
- [x] Run a production build.
- [x] Verify desktop, tablet, and mobile layouts in-browser.
- [x] Verify keyboard, focus, redirecting, error, and reduced-motion states.
- [ ] Confirm the production client bundle contains no backend secret.
