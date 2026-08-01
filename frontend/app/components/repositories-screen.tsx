"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import type {
  RepositoryFilters,
  RepositoryListView,
  Repository,
} from "../lib/repositories";
import { filterRepositories, mapRepository } from "../lib/repositories";
import {
  fetchGitHubRepos,
  fetchIntegrationRepos,
  fetchIntegrations,
  fetchProjects,
  launchProject,
  Project,
} from "../lib/api";
import { ApiError } from "../lib/api-errors";
import { Spinner } from "./ui";

type RepositoriesScreenProps = {
  filters: RepositoryFilters;
};

const STATE_LABELS: Record<Repository["projectState"], string> = {
  available: "Available",
  provisioning: "Provisioning",
  ready: "Ready",
  failed: "Failed",
};

const REPOSITORIES_STATE_CONTENT: Record<
  "no-repositories" | "error" | "unauthorized",
  {
    eyebrow: string;
    title: string;
    description: string;
    actionLabel: string;
    actionHref: string;
  }
> = {
  "no-repositories": {
    eyebrow: "No repositories yet",
    title: "Connect a provider to see your repositories here.",
    description:
      "Visit Integrations to connect GitHub, GitLab, or GitBucket and grant Graphify access to the repositories you want to use.",
    actionLabel: "Go to Integrations",
    actionHref: "/integrations",
  },
  error: {
    eyebrow: "Repository sync unavailable",
    title: "Graphify could not load your repositories.",
    description:
      "The connection may be temporarily unavailable. Retry the request; your access and existing workspaces are unchanged.",
    actionLabel: "Retry",
    actionHref: "/repositories",
  },
  unauthorized: {
    eyebrow: "Connection expired",
    title: "Your GitHub connection needs to be reconnected.",
    description:
      "Graphify could not use your stored GitHub access token. Reconnect from Integrations to keep browsing repositories.",
    actionLabel: "Go to Integrations",
    actionHref: "/integrations",
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

function RepositoryAction({ repository }: { repository: Repository }) {
  const router = useRouter();
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (repository.projectState === "provisioning") {
    return (
      <Link
        className="repository-action"
        href={`/projects/${repository.workspaceId}/launch`}
      >
        Provisioning
      </Link>
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

  async function handleLaunch() {
    setError(null);
    setLaunching(true);
    try {
      const result = await launchProject({
        repoFullName: `${repository.owner}/${repository.name}`,
        repoUrl: repository.htmlUrl,
        provider: repository.provider,
        defaultBranch: repository.defaultBranch,
      });
      router.push(`/projects/${result.project_id}/launch`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start extraction");
      setLaunching(false);
    }
  }

  return (
    <span className="repository-action-group">
      <button
        className={`repository-action ${isRetry ? "is-retry" : "is-primary"}`}
        type="button"
        disabled={launching}
        onClick={handleLaunch}
      >
        {launching ? "Starting…" : isRetry ? "Retry" : "Launch Workspace"}
      </button>
      {error && <span className="repository-action-error">{error}</span>}
    </span>
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
            <span className="repository-provider-badge">{repository.provider}</span>
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

function RepositoriesEmptyState({
  content,
}: {
  content: (typeof REPOSITORIES_STATE_CONTENT)[keyof typeof REPOSITORIES_STATE_CONTENT];
}) {
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

async function loadRepositories(): Promise<Repository[]> {
  const [projects, integrations] = await Promise.all([
    fetchProjects().catch(() => [] as Project[]),
    fetchIntegrations().catch(() => []),
  ]);

  const projectsByRepoName = new Map(projects.map((p) => [p.repo_name, p]));

  const providerFetches: Promise<Repository[]>[] = [
    fetchGitHubRepos().then((repos) =>
      repos.map((r) => mapRepository(r, "github", projectsByRepoName)),
    ),
  ];

  for (const integration of integrations) {
    if (integration.status === "connected" && integration.id !== "github") {
      const provider = integration.id as "gitlab" | "gitbucket";
      providerFetches.push(
        fetchIntegrationRepos(provider)
          .then((repos) => repos.map((r) => mapRepository(r, provider, projectsByRepoName)))
          .catch(() => []),
      );
    }
  }

  const results = await Promise.all(providerFetches);
  return results.flat();
}

export function RepositoriesScreen({ filters }: RepositoriesScreenProps) {
  const [repositories, setRepositories] = useState<Repository[] | null>(null);
  const [view, setView] = useState<RepositoryListView | "unauthorized">("list");

  useEffect(() => {
    let cancelled = false;

    loadRepositories()
      .then((repos) => {
        if (cancelled) return;
        setRepositories(repos);
        setView(repos.length === 0 ? "no-repositories" : "list");
      })
      .catch((error) => {
        if (cancelled) return;
        setRepositories([]);
        setView(error instanceof ApiError && error.isUnauthorized ? "unauthorized" : "error");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(
    () => filterRepositories(repositories ?? [], filters),
    [repositories, filters],
  );

  const hasFilters =
    filters.query !== "" || filters.ownership !== "all" || filters.state !== "all";

  if (repositories === null) {
    return (
      <main className="dashboard-page">
        <div className="dashboard-loading-shell">
          <Spinner size="lg" label="Loading repositories" />
        </div>
      </main>
    );
  }

  if (view === "no-repositories" || view === "error" || view === "unauthorized") {
    return (
      <main className="dashboard-page">
        <RepositoriesEmptyState content={REPOSITORIES_STATE_CONTENT[view]} />
      </main>
    );
  }

  const totalWorkspaceCount = repositories.filter((r) => r.workspaceId).length;

  return (
    <main className="dashboard-page">
      <div className="dashboard-shell">
        <section className="dashboard-heading" aria-labelledby="dashboard-title">
          <div>
            <p className="dashboard-eyebrow">Repositories</p>
            <h1 id="dashboard-title">Choose where to work.</h1>
            <p>
              Launch a new Graphify workspace or return to a repository you
              have already indexed.
            </p>
          </div>
          <dl className="dashboard-summary">
            <div>
              <dt>Repositories</dt>
              <dd>{repositories.length.toString().padStart(2, "0")}</dd>
            </div>
            <div>
              <dt>Workspaces</dt>
              <dd>{totalWorkspaceCount.toString().padStart(2, "0")}</dd>
            </div>
          </dl>
        </section>

        <form className="dashboard-filters" action="/repositories">
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
            <Link className="dashboard-clear-filters" href="/repositories">
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

          {filtered.length > 0 ? (
            filtered.map((repository) => (
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
              <Link className="action-secondary" href="/repositories">
                Clear filters
              </Link>
            </div>
          )}
        </section>

        <footer className="dashboard-footer">
          <span>
            Showing {filtered.length} of {repositories.length} repositories
          </span>
          <Link href="/integrations">Manage connections</Link>
        </footer>
      </div>
    </main>
  );
}
