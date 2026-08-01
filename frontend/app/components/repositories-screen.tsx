import Image from "next/image";
import Link from "next/link";
import type {
  DashboardFilters,
  DashboardView,
  Repository,
  RepositoryProjectState,
} from "../lib/dashboard";
import { BrandLockup } from "./brand-lockup";

type DashboardScreenProps = {
  filters: DashboardFilters;
  repositories: Repository[];
  totalRepositoryCount: number;
  totalWorkspaceCount: number;
  view: DashboardView;
};

const STATE_LABELS: Record<RepositoryProjectState, string> = {
  available: "Available",
  provisioning: "Provisioning",
  ready: "Ready",
  failed: "Failed",
};

const DASHBOARD_STATE_CONTENT: Record<
  Exclude<DashboardView, "list" | "syncing">,
  {
    eyebrow: string;
    title: string;
    description: string;
    actionLabel: string;
    actionHref: string;
  }
> = {
  "no-installation": {
    eyebrow: "GitHub connection required",
    title: "Install the GitHub App to discover repositories.",
    description:
      "Graphify only lists repositories you explicitly select during installation. Existing project data is not affected.",
    actionLabel: "Connect GitHub",
    actionHref: "/onboarding/github",
  },
  "no-repositories": {
    eyebrow: "No repository access",
    title: "Choose the repositories you want to use with Graphify.",
    description:
      "The GitHub App is installed, but no repositories are selected. Update the installation to continue.",
    actionLabel: "Configure repository access",
    actionHref: "/onboarding/github?state=no-repositories",
  },
  error: {
    eyebrow: "Repository sync unavailable",
    title: "Graphify could not load your repositories.",
    description:
      "The connection may be temporarily unavailable. Retry the request; your GitHub access and existing workspaces are unchanged.",
    actionLabel: "Retry",
    actionHref: "/dashboard",
  },
  "rate-limited": {
    eyebrow: "GitHub limit reached",
    title: "Repository sync is paused for a little while.",
    description:
      "GitHub asked Graphify to slow down. Your existing workspaces remain available, and repository sync can resume after the limit resets.",
    actionLabel: "View existing repositories",
    actionHref: "/dashboard",
  },
};

function SearchIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <circle cx="8.5" cy="8.5" r="5.5" />
      <path d="m12.5 12.5 4 4" />
    </svg>
  );
}

function SyncIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <path d="M16 6.5A7 7 0 0 0 4.1 4.8L2.5 6.5M4 13.5a7 7 0 0 0 11.9 1.7l1.6-1.7" />
      <path d="M2.5 2.5v4h4M17.5 17.5v-4h-4" />
    </svg>
  );
}

function RepositoryAction({ repository }: { repository: Repository }) {
  if (repository.projectState === "provisioning") {
    return (
      <span className="repository-action is-disabled" aria-disabled="true">
        Provisioning
      </span>
    );
  }

  if (repository.projectState === "ready" && repository.workspaceId) {
    return (
      <Link
        className="repository-action"
        href={`/workspace/${repository.workspaceId}`}
      >
        Resume Workspace
      </Link>
    );
  }

  const isRetry = repository.projectState === "failed";
  const projectId = repository.workspaceId ?? repository.id;

  return (
    <Link
      className={`repository-action ${isRetry ? "is-retry" : "is-primary"}`}
      href={`/projects/${projectId}/launch`}
    >
      {isRetry ? "Retry" : "Launch Workspace"}
    </Link>
  );
}

function RepositoryRow({ repository }: { repository: Repository }) {
  return (
    <article className="repository-row">
      <div className="repository-identity">
        <div className="repository-mark" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div>
          <h2>
            <span>{repository.owner}/</span>
            {repository.name}
          </h2>
          <div className="repository-tags">
            <span>{repository.visibility}</span>
            <span>{repository.defaultBranch}</span>
            <span className="repository-language">
              <i className={`is-${repository.languageTone}`} />
              {repository.language}
            </span>
          </div>
        </div>
      </div>

      <dl className="repository-timing">
        <div>
          <dt>Last push</dt>
          <dd>{repository.lastPushedLabel}</dd>
        </div>
        <div>
          <dt>Last indexed</dt>
          <dd>{repository.lastIndexedLabel ?? "Not indexed"}</dd>
        </div>
      </dl>

      <div className="repository-state">
        <span
          className={`repository-state-badge is-${repository.projectState}`}
        >
          <i aria-hidden="true" />
          {STATE_LABELS[repository.projectState]}
        </span>
        <RepositoryAction repository={repository} />
      </div>
    </article>
  );
}

function DashboardEmptyState({
  view,
}: {
  view: Exclude<DashboardView, "list" | "syncing">;
}) {
  const content = DASHBOARD_STATE_CONTENT[view];

  return (
    <section className="dashboard-empty-state" aria-labelledby="empty-title">
      <div className="dashboard-empty-graphic" aria-hidden="true">
        <span />
        <span />
        <span />
        <i />
      </div>
      <p className="dashboard-eyebrow">{content.eyebrow}</p>
      <h1 id="empty-title">{content.title}</h1>
      <p>{content.description}</p>
      <Link className="action-primary" href={content.actionHref}>
        {content.actionLabel}
      </Link>
    </section>
  );
}

export function DashboardScreen({
  filters,
  repositories,
  totalRepositoryCount,
  totalWorkspaceCount,
  view,
}: DashboardScreenProps) {
  if (view !== "list" && view !== "syncing") {
    return (
      <main className="dashboard-page">
        <DashboardHeader isSyncing={false} />
        <DashboardEmptyState view={view} />
      </main>
    );
  }

  const hasFilters =
    filters.query !== "" ||
    filters.ownership !== "all" ||
    filters.state !== "all";

  return (
    <main className="dashboard-page">
      <DashboardHeader isSyncing={view === "syncing"} />

      <div className="dashboard-shell">
        <section className="dashboard-heading" aria-labelledby="dashboard-title">
          <div>
            <p className="dashboard-eyebrow">Repository dashboard</p>
            <h1 id="dashboard-title">Choose where to work.</h1>
            <p>
              Launch a new Graphify workspace or return to a repository you
              have already indexed.
            </p>
          </div>
          <dl className="dashboard-summary">
            <div>
              <dt>Repositories</dt>
              <dd>{totalRepositoryCount.toString().padStart(2, "0")}</dd>
            </div>
            <div>
              <dt>Workspaces</dt>
              <dd>{totalWorkspaceCount.toString().padStart(2, "0")}</dd>
            </div>
          </dl>
        </section>

        {view === "syncing" && (
          <div className="dashboard-sync-notice" role="status">
            <SyncIcon />
            <div>
              <strong>Syncing repositories from GitHub</strong>
              <span>
                The list stays available while Graphify checks for changes.
              </span>
            </div>
          </div>
        )}

        <form className="dashboard-filters" action="/dashboard">
          <label className="dashboard-search">
            <span className="sr-only">Search repositories</span>
            <SearchIcon />
            <input
              defaultValue={filters.query}
              name="q"
              placeholder="Search repositories or languages"
              type="search"
            />
          </label>

          <label>
            <span>Ownership</span>
            <select defaultValue={filters.ownership} name="ownership">
              <option value="all">All repositories</option>
              <option value="personal">Personal</option>
              <option value="organization">Organizations</option>
            </select>
          </label>

          <label>
            <span>State</span>
            <select defaultValue={filters.state} name="state">
              <option value="all">All states</option>
              <option value="available">Available</option>
              <option value="provisioning">Provisioning</option>
              <option value="ready">Ready</option>
              <option value="failed">Failed</option>
            </select>
          </label>

          <button type="submit">Apply filters</button>
          {hasFilters && (
            <Link className="dashboard-clear-filters" href="/dashboard">
              Clear
            </Link>
          )}
        </form>

        <section className="repository-list" aria-label="Repositories">
          <header className="repository-list-header">
            <span>Repository</span>
            <span>Activity</span>
            <span>Graphify state</span>
          </header>

          {repositories.length > 0 ? (
            repositories.map((repository) => (
              <RepositoryRow key={repository.id} repository={repository} />
            ))
          ) : (
            <div className="dashboard-no-results">
              <p className="dashboard-eyebrow">No matches</p>
              <h2>No repositories match these filters.</h2>
              <p>
                Try a different repository name, ownership group, or workspace
                state.
              </p>
              <Link className="action-secondary" href="/dashboard">
                Clear filters
              </Link>
            </div>
          )}
        </section>

        <footer className="dashboard-footer">
          <span>
            Showing {repositories.length} of {totalRepositoryCount} repositories
          </span>
          <Link href="/onboarding/github?state=connected">
            Manage GitHub access
          </Link>
        </footer>
      </div>
    </main>
  );
}

function DashboardHeader({ isSyncing }: { isSyncing: boolean }) {
  return (
    <header className="dashboard-header">
      <BrandLockup priority />
      <nav aria-label="Dashboard navigation">
        <span className={`dashboard-sync-status ${isSyncing ? "is-syncing" : ""}`}>
          <i aria-hidden="true" />
          {isSyncing ? "Syncing GitHub" : "GitHub synced"}
        </span>
        <Link href="/admin/credentials">Admin</Link>
        <details className="dashboard-user-menu">
          <summary aria-label="Open user menu">
            <Image src="/github-mark.svg" alt="" width={16} height={16} />
            <span>maya-chen</span>
          </summary>
          <div>
            <strong>Maya Chen</strong>
            <span>maya@graphify.dev</span>
            <Link href="/">Sign out</Link>
          </div>
        </details>
      </nav>
    </header>
  );
}
