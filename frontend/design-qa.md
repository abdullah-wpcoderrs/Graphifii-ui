# Graphify authentication screen — design QA

## Evidence

- Source visual truth:
  `docs/reference-captures/kodus-signup-qa-normalized.jpg`
- Source motion states:
  `docs/reference-captures/kodus-motion-frame-a.jpg`,
  `docs/reference-captures/kodus-motion-frame-b.jpg`, and
  `docs/reference-captures/kodus-motion-frame-c.jpg`
- Implementation:
  `docs/reference-captures/graphify-auth-740x967.jpg`
- Desktop implementation:
  `docs/reference-captures/graphify-auth-desktop-final.jpg`
- Mobile implementation:
  `docs/reference-captures/graphify-auth-mobile-final.jpg`
- Matched comparison viewport: `740 × 967` CSS pixels.
- Matched comparison pixels: `740 × 967` for both normalized source and
  implementation.
- Density normalization: browser captures were normalized to `740 × 967`
  pixels with contain-fit and the Graphify app background. The implementation
  capture used device scale factor `1`.
- Desktop verification viewport: `1280 × 720` CSS pixels, device scale factor
  `1`.
- Mobile verification viewport: `390 × 844` CSS pixels, device scale factor
  `1`.
- State: ready, animated workspace preview active.

## Full-view comparison

The final comparison preserves the source structure: a dark two-column auth
composition, brand and product story on the left, stable authentication
content on the right, a full-width provider action, and muted supporting copy.
Graphify intentionally replaces the Kodus multi-provider/email form with the
single GitHub App action required by the product specification.

At `1280 × 720`, the implementation fills the viewport without vertical or
horizontal overflow. At `740 × 967`, it preserves the split composition. At
`390 × 844`, it stacks into a readable single-column flow instead of repeating
the source page's horizontal clipping.

## Focused region comparison

A separate focused crop was not required because the provider button, form
copy, product preview, logo, and typographic hierarchy are legible in the
`740 × 967` full-view comparison. The GitHub mark was also inspected at its
rendered control size.

## Required fidelity surfaces

- Fonts and typography: Geist/Geist Mono provide the specified Graphify
  hierarchy. Display copy, body copy, technical labels, and the provider
  action have distinct weights and readable line heights.
- Spacing and layout rhythm: the source's panel/form grouping and stable form
  alignment are preserved. Structural surfaces use Graphify's sharp geometry;
  controls use the documented `6px` radius.
- Colors and tokens: all main surfaces, borders, text, focus, primary action,
  graph selection, and god-node accents use documented Graphify tokens.
- Image quality and asset fidelity: the GitHub control uses the captured real
  provider mark. The Graphify wordmark uses the generated, locally stored
  `public/graphify-mark.png` raster asset with transparency. No source asset is
  hotlinked.
- Copy and content: all app-specific text describes the Graphify GitHub App
  flow, repository permissions, graph creation, and reviewable pull requests.
- Interaction and accessibility: the primary button is semantic, keyboard
  reachable, exposes a visible `2px` blue focus ring with `3px` offset,
  prevents duplicate redirect clicks, and shows a redirecting label/spinner.
  Reduced-motion preferences stop non-essential looping animation.

## Comparison history

### Iteration 1

- [P2] The first desktop implementation overflowed the `1280 × 720` viewport
  by `33px`.
  Fix: reduced the story-panel vertical gaps and preview height and constrained
  the layout to the viewport.
  Post-fix evidence: desktop scroll size is exactly `1280 × 720`.
- [P2] The first wordmark used a CSS-drawn placeholder mark.
  Fix: generated a distinct Graphify raster mark, removed its chroma key,
  optimized its transparent bounds, and stored it locally.
  Post-fix evidence: `docs/reference-captures/graphify-auth-desktop-final.jpg`.

### Iteration 2

- [P2] The first responsive pass stacked the layout at the reference's narrow
  desktop/tablet width.
  Fix: moved the stack breakpoint to `640px` and added a compact split layout
  for widths between `641px` and `900px`.
  Post-fix evidence: `docs/reference-captures/graphify-auth-740x967.jpg`.

## Browser verification

- Primary GitHub action: attempted navigation to
  `http://localhost:8000/api/auth/github/login`; the backend is not running,
  so the destination correctly returned connection refused.
- Keyboard focus: verified on the primary button.
- Console errors and warnings: none on desktop or mobile.
- Responsive overflow: none at `1280 × 720`, `740 × 967`, or `390 × 844`.
- Production build: passed.

## Findings

No actionable P0, P1, or P2 differences remain. The mobile stack is an
intentional product requirement and corrects a clipping defect in the source.

## Follow-up polish

- [P3] Revisit the generated Graphify mark if a formal brand asset is supplied.
- [P3] Replace the local redirect destination with the live Railway
  authentication service when the backend endpoint exists.

final result: passed

# Graphify provisioning and workspace — design QA

## Evidence

- Source explorer visual truth:
  `/Users/mac/Desktop/Screenshot 2026-07-31 at 3.06.43 AM.png`.
- Implementation full view:
  `docs/reference-captures/workspace-explorer-implementation.png`.
- Implementation focused explorer:
  `docs/reference-captures/workspace-explorer-focused.png`.
- Combined visual comparison:
  `docs/reference-captures/workspace-explorer-comparison.png`.
- Source pixels: `600 × 734`; implementation pixels and CSS viewport:
  `1024 × 800`, device scale factor `1`.
- Focused implementation region: `180 × 716` pixels.
- Density normalization: the source is a high-density reference capture and
  was kept at native resolution; the implementation was kept at its actual
  workspace width in the combined comparison so interface density was not
  artificially equalized.
- State: workspace ready, Editor panel active, `query.py` selected, all file
  groups expanded.

## Full-view comparison

The workspace preserves the requested IDE composition: repository context,
responsive workspace tabs, file explorer, Monaco editor, architecture graph,
and graph-aware agent. Desktop uses three simultaneously visible resizable
panes; narrower screens expose one pane at a time without horizontal overflow.

Provisioning exposes explicit phase progress, live event history, failure and
retry recovery, and a single terminal redirect into the workspace.

## Focused region comparison

The combined comparison verifies the explorer against the supplied reference.
Both use an uppercase Explorer label, disclosure chevrons, open-folder icons,
indented child files, muted filenames, and a compact active row. The
implementation intentionally retains Graphify's smaller workspace density and
adds modified-file dots. Python files use a recognizable Python mark, Markdown
uses a distinct Markdown mark, and unknown languages fall back to a generic
file icon.

## Required fidelity surfaces

- Fonts and typography: workspace chrome uses the existing Geist/Geist Mono
  hierarchy. Explorer labels and filenames remain readable at compact IDE
  sizes with ellipsis for constrained names.
- Spacing and layout rhythm: explorer rows use a consistent `30px` rhythm,
  folder/file indentation, and aligned `11px–16px` glyph slots.
- Colors and tokens: the explorer reuses Graphify panel, text, border, active,
  and modified-state tokens. Orange folders and blue file-type marks mirror
  the reference without overriding semantic state colors.
- Image quality and asset fidelity: there are no raster image assets in this
  component. File, folder, and disclosure glyphs come from the maintained
  React Icons library; no placeholder glyphs or CSS-drawn icons remain.
- Copy and content: folders and files reflect the Graphify fixture repository,
  including `graphify`, `server`, Python sources, and `README.md`.
- Interaction and accessibility: native disclosure summaries collapse and
  reopen folders, file rows are semantic buttons, selected files update Monaco
  and the active editor tab, and the file type is never the only textual
  identifier.

## Comparison history

### Iteration 1

- [P2] The initial explorer used the same generic document outline for every
  file, so language identity was absent.
  Fix: introduced extension/language-aware icons and open-folder/disclosure
  icons using React Icons.
  Post-fix evidence:
  `docs/reference-captures/workspace-explorer-comparison.png`.
- [P2] The initial explorer was too compressed to preserve the reference's
  folder/file hierarchy.
  Fix: widened the desktop explorer and established a `30px` row rhythm with
  clearer indentation.
  Post-fix evidence:
  `docs/reference-captures/workspace-explorer-focused.png`.

## Browser verification

- Folder disclosure: collapse and reopen passed.
- File selection: selecting `README.md` updated the active row, editor tab,
  and Markdown icon; `query.py` was restored afterward.
- Shared workspace interactions verified: graph-to-editor selection, Monaco
  diff inspection, agent streaming/stop state, output filtering, and pane
  resizing.
- Responsive overflow: none at the verified desktop, tablet, and mobile
  workspace widths.
- Console errors and warnings: none in the clean workspace verification.
- ESLint, TypeScript validation, `git diff --check`, and the production build
  pass.

## Findings

No actionable P0, P1, or P2 differences remain. The narrower implementation
explorer is an intentional constraint of the three-pane Graphify shell.

## Follow-up polish

- [P3] Add explicit icon mappings as new languages enter the repository
  contract.

final result: passed

# Graphify repository dashboard — design QA

## Evidence

- Implementation: `app/dashboard/page.tsx`,
  `app/components/dashboard-screen.tsx`, and `app/lib/dashboard.ts`.
- Desktop verification viewport: `1440 × 1000` CSS pixels.
- Tablet verification viewport: `1024 × 800` CSS pixels.
- Reported regression viewport: `921 × 967` CSS pixels.
- Mobile verification viewport: `390 × 844` CSS pixels.
- States verified: repository list, filtered list, no results, syncing, and
  backend error.

## Browser verification

- URL-backed search and ownership filters submit the expected values and keep
  their selected state after navigation.
- Desktop rows use a contained state/action stack between `861px` and
  `1100px`, then adapt to repository cards below the `860px` breakpoint.
- At the reported `921 × 967` viewport, all five repository actions are fully
  inside the repository panel with no horizontal scroll.
- Sync state keeps repositories usable while exposing an ARIA live status.
- No-results and error states expose clear recovery actions.
- Responsive overflow: none at desktop, tablet, or mobile widths.
- Console errors and warnings: none in the clean verification session.
- ESLint, TypeScript validation, `git diff --check`, and the production build
  pass.

## Findings

No actionable P0, P1, or P2 differences remain. The hybrid dense-row/card
behavior reconciles the PRD's repository-card requirement with the
implementation blueprint's high-density authenticated dashboard.

final result: passed
