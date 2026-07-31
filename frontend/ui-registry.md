# Graphify UI registry

### Authentication composition

File: `app/components/auth-screen.tsx`
Last updated: 2026-07-31

| Property | Class / token |
| --- | --- |
| Background | `--bg-app`, `--bg-panel`, `--bg-editor` |
| Border | `1px solid var(--border-subtle)` |
| Border radius | Structural panels `0`; controls `6px` |
| Text — primary | `--text-primary` |
| Text — secondary | `--text-secondary`, `--text-muted` |
| Spacing | Page `24px`; story `48px`; compact layout `28px`; mobile `24px` |
| Hover state | Emerald brightness lift and `translateY(-1px)` |
| Shadow | Preview only: `0 24px 70px rgb(0 0 0 / 26%)` |
| Accent usage | Emerald primary; blue selection/focus; purple graph-node emphasis |

**Pattern notes:**

Authentication follows a story/form split at desktop and tablet sizes and
stacks below `640px`. Main structural surfaces stay sharp. Product motion is
contained inside the workspace preview so authentication content remains
stable.

### Primary authentication button

File: `app/components/auth-screen.tsx`
Last updated: 2026-07-31

| Property | Class / token |
| --- | --- |
| Background | `--accent-emerald` |
| Border | `1px solid rgb(255 255 255 / 7%)` |
| Border radius | `6px` |
| Text — primary | `#06110d` |
| Text — secondary | none |
| Spacing | `min-height: 50px`; `padding: 0 22px`; `gap: 10px` |
| Hover state | `#34d399`, elevated shadow, `translateY(-1px)` |
| Shadow | `0 10px 32px rgb(16 185 129 / 16%)` on hover |
| Accent usage | Primary emerald action |

**Pattern notes:**

Primary authentication actions are full-width, use the real provider mark,
show a visible blue focus ring, and disable immediately when redirecting.

### Recovery screen

File: `app/components/recovery-screen.tsx`
Last updated: 2026-07-31

| Property | Class / token |
| --- | --- |
| Background | Page `--bg-app`; shell `--bg-panel` |
| Border | `1px solid var(--border-subtle)` |
| Border radius | Structural shell `0`; actions `6px` |
| Text — primary | `--text-primary` |
| Text — secondary | `--text-secondary`, `--text-muted` |
| Spacing | Page `24px`; shell `clamp(28px, 5vw, 56px)`; content `clamp(54px, 8vw, 86px)` |
| Hover state | Primary emerald lift; secondary border and surface lift |
| Shadow | none |
| Accent usage | Emerald eyebrow and guidance indicator; oversized muted mono code |

**Pattern notes:**

Authentication errors and 404 states share one quiet recovery composition.
Error copy is allow-listed, references are sanitized, and technical details
stay outside the browser. The root 500 boundary mirrors this composition with
inline tokens because it replaces the application layout.

### GitHub installation card

File: `app/components/onboarding-screen.tsx`
Last updated: 2026-07-31

| Property | Class / token |
| --- | --- |
| Background | Card `--bg-panel`; side rail `--bg-editor` |
| Border | `1px solid var(--border-subtle)` |
| Border radius | Card `0`; status badge `16px`; actions `6px` |
| Text — primary | `--text-primary` |
| Text — secondary | `--text-secondary`, `--text-muted` |
| Spacing | Card sections `22px`; layout sections `clamp(34px, 7vw, 84px)` |
| Hover state | Shared primary and secondary action patterns |
| Shadow | none |
| Accent usage | Emerald for connected/progress; amber pending; red repair states |

**Pattern notes:**

Repository permissions are shown before the primary action. Installation
health is expressed through a compact mono badge, while the adjacent checklist
keeps identity, installation, and repository access visibly distinct.

### Repository dashboard list

File: `app/components/dashboard-screen.tsx`
Last updated: 2026-07-31

| Property | Class / token |
| --- | --- |
| Background | Page `--bg-app`; toolbar/list `--bg-panel`; list header `--bg-editor` |
| Border | `1px solid var(--border-subtle)` |
| Border radius | Structural list and rows `0`; controls/actions `6px`; state badges `14px` |
| Text — primary | `--text-primary`; technical identity `--font-code` |
| Text — secondary | `--text-secondary`, `--text-muted` |
| Spacing | Shell `64px` inset; toolbar `14px`; repository rows `19px 20px` |
| Hover state | Row surface lift; action border/surface lift; emerald primary lift |
| Shadow | User menu only: `0 18px 48px rgb(0 0 0 / 32%)` |
| Accent usage | Emerald ready/available; blue provisioning; red failed; purple graph mark |

**Pattern notes:**

Repository collections use a dense three-column row at desktop. Between
`861px` and `1100px`, state and action controls stack inside a contained
tablet-width column; below `860px`, rows become cards. Repository identity
remains the first visual anchor, technical state uses compact mono badges, and
every row exposes exactly one launch, resume, retry, or disabled provisioning
action.

### Dashboard filter toolbar

File: `app/components/dashboard-screen.tsx`
Last updated: 2026-07-31

| Property | Class / token |
| --- | --- |
| Background | Toolbar `--bg-panel`; controls `--bg-input` |
| Border | Toolbar and controls `1px solid var(--border-subtle)` |
| Border radius | Toolbar `0`; inputs, selects, and button `6px` |
| Text — primary | `--text-primary` |
| Text — secondary | Labels and placeholders `--text-muted` |
| Spacing | Toolbar `14px`; controls `38px` height; `10px` gap |
| Hover state | Focus-border lift for controls; emerald lift for apply action |
| Shadow | none |
| Accent usage | Emerald apply action; blue global focus ring |

**Pattern notes:**

Repository filters submit as URL search parameters so selections survive
reloads and remain shareable. Mobile toolbars stack into one column while
retaining full-width, minimum `38px` controls.

### Workspace provisioning progress

File: `app/components/provisioning-screen.tsx`
Last updated: 2026-07-31

| Property | Class / token |
| --- | --- |
| Background | Page `--bg-app`; event rail `--bg-editor`; header `--bg-panel` |
| Border | Structural divisions `1px solid var(--border-subtle)` |
| Border radius | Structure `0`; branch/recovery controls `6px`; phase markers circular |
| Text — primary | `--text-primary`; phase/event data `--font-code` |
| Text — secondary | `--text-secondary`, `--text-muted` |
| Spacing | Main `clamp(36px, 6vw, 72px)`; event rail `22px`; phases `62px` rhythm |
| Hover state | Emerald retry action; secondary dashboard recovery lift |
| Shadow | Progress glow only: `rgb(16 185 129 / 28%)` |
| Accent usage | Emerald complete; blue active; red failure |

**Pattern notes:**

Long-running backend work pairs a stable phase list with a compact live-event
rail. Progress is numerical and semantic, terminal states occur once, and
failure language never claims that partial artifacts were persisted.

### Three-pane workspace shell

File: `app/components/workspace-shell.tsx`
Last updated: 2026-07-31

| Property | Class / token |
| --- | --- |
| Background | Editor `--bg-editor`; graph `--bg-app`; agent `--bg-panel` |
| Border | `1px solid var(--border-subtle)` panel separators |
| Border radius | Structural panes `0`; compact controls `4px–6px`; composer `10px` |
| Text — primary | `--text-primary`; code and state `--font-code` |
| Text — secondary | `--text-secondary`, `--text-muted` |
| Spacing | Header `44px`; pane tools `36px–44px`; dense internal padding `8px–12px` |
| Hover state | Blue active views; emerald primary PR action; visible resize affordance |
| Shadow | Graph nodes only: `0 10px 30px rgb(0 0 0 / 25%)` |
| Accent usage | Emerald ready/PR; blue selection; purple graph centrality |

**Pattern notes:**

Desktop workspaces preserve Editor/Graph/Agent simultaneously with persisted
resizable bounds. At `1100px` and below, the same state is exposed through
one active panel at a time; repository and branch identity remain fixed.

### Workspace file explorer

File: `app/components/workspace-shell.tsx`
Last updated: 2026-07-31

| Property | Class / token |
| --- | --- |
| Background | Explorer `--bg-panel`; active row `rgb(255 255 255 / 4%)` |
| Border | Right divider and header `--border-subtle`; active inset blue |
| Border radius | none |
| Text — primary | Folder `#d4d4d8`; selected file `--text-primary` |
| Text — secondary | File `--text-muted` |
| Spacing | Folder/file rows `30px`; file indent `33px`; icon slots `11px–16px` |
| Hover state | Subtle raised row; blue inset selection |
| Shadow | none |
| Accent usage | Orange folders; blue Python/Markdown; blue modified dot |

**Pattern notes:**

Explorer trees use native `details`/`summary` disclosure, a real icon-library
glyph for every visible icon, and language-aware file mappings with a neutral
fallback. File identity remains consistent in explorer rows, editor tabs, and
proposed-change lists.

### Architecture graph node

File: `app/components/architecture-graph.tsx`
Last updated: 2026-07-31

| Property | Class / token |
| --- | --- |
| Background | Node `--bg-input`; canvas `--bg-app` |
| Border | Standard `--border-subtle`; god node purple; selected node blue `2px` |
| Border radius | Node/control `6px`; inspector `0` |
| Text — primary | Label `--text-primary`; metadata `--text-muted` |
| Spacing | Node `9px 10px`; inspector `10px 12px` |
| Hover state | Edges and active selections use `--accent-blue` |
| Shadow | Node `0 10px 30px rgb(0 0 0 / 25%)` |
| Accent usage | Purple centrality; blue selection/file match |

**Pattern notes:**

Graph selection is bidirectional with source selection. Node type, source
path, community, and centrality remain distinct without relying on color alone.

### Graph-aware agent composer

File: `app/components/workspace-shell.tsx`
Last updated: 2026-07-31

| Property | Class / token |
| --- | --- |
| Background | Composer `--bg-input`; conversation `--bg-panel` |
| Border | `1px solid var(--border-subtle)` |
| Border radius | Composer `10px`; send/stop `6px`; suggestions `14px` |
| Text — primary | `--text-primary`; messages `#d4d4d8` |
| Text — secondary | `--text-muted` |
| Spacing | Composer/message cards `10px–12px`; suggestion gap `6px` |
| Hover state | Blue send; bordered suggestions; clear disabled send state |
| Shadow | none |
| Accent usage | Purple graph context; blue user/selection; emerald proposed action |

**Pattern notes:**

Agent work remains subordinate to review: graph context is visible, streaming
can be stopped, proposed files are enumerated, and diff inspection precedes PR
preparation.
