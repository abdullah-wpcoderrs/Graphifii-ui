import type { Project, RemoteRepository } from "./api";

export type RepositoryOwnership = "personal" | "organization";

export type RepositoryProjectState =
  | "available"
  | "provisioning"
  | "ready"
  | "failed";

export type Repository = {
  id: string;
  owner: string;
  name: string;
  visibility: "public" | "private";
  ownership: RepositoryOwnership;
  defaultBranch: string;
  htmlUrl: string;
  language: string;
  languageTone: "blue" | "purple" | "amber" | "cyan";
  lastPushedLabel: string;
  projectState: RepositoryProjectState;
  lastIndexedLabel: string | null;
  workspaceId: string | null;
  provider: "github" | "gitlab" | "gitbucket";
};

export type RepositoryListView = "list" | "no-repositories" | "error";

export type RepositoryFilters = {
  query: string;
  ownership: "all" | RepositoryOwnership;
  state: "all" | RepositoryProjectState;
};

const OWNERSHIP_FILTERS = new Set<RepositoryFilters["ownership"]>([
  "all",
  "personal",
  "organization",
]);

const STATE_FILTERS = new Set<RepositoryFilters["state"]>([
  "all",
  "available",
  "provisioning",
  "ready",
  "failed",
]);

function firstValue(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

export function getRepositoryFilters(params: {
  q?: string | string[];
  ownership?: string | string[];
  state?: string | string[];
}): RepositoryFilters {
  const ownership = firstValue(params.ownership);
  const state = firstValue(params.state);

  return {
    query: (firstValue(params.q) ?? "").trim().slice(0, 120),
    ownership: OWNERSHIP_FILTERS.has(
      ownership as RepositoryFilters["ownership"],
    )
      ? (ownership as RepositoryFilters["ownership"])
      : "all",
    state: STATE_FILTERS.has(state as RepositoryFilters["state"])
      ? (state as RepositoryFilters["state"])
      : "all",
  };
}

export function filterRepositories(
  repositories: Repository[],
  filters: RepositoryFilters,
) {
  const query = filters.query.toLocaleLowerCase();

  return repositories.filter((repository) => {
    const matchesQuery =
      !query ||
      `${repository.owner}/${repository.name}`
        .toLocaleLowerCase()
        .includes(query) ||
      repository.language.toLocaleLowerCase().includes(query);
    const matchesOwnership =
      filters.ownership === "all" ||
      repository.ownership === filters.ownership;
    const matchesState =
      filters.state === "all" || repository.projectState === filters.state;

    return matchesQuery && matchesOwnership && matchesState;
  });
}

const LANGUAGE_TONES: Repository["languageTone"][] = [
  "blue",
  "purple",
  "amber",
  "cyan",
];

/** Deterministic (not random) so the same language always renders the same tone. */
function languageTone(language: string): Repository["languageTone"] {
  let hash = 0;
  for (let i = 0; i < language.length; i++) {
    hash = (hash * 31 + language.charCodeAt(i)) | 0;
  }
  return LANGUAGE_TONES[Math.abs(hash) % LANGUAGE_TONES.length];
}

export function formatRelativeTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;

  const diffMs = Date.now() - then;
  const diffMinutes = Math.round(diffMs / 60_000);

  if (diffMinutes < 1) return "Just now";
  if (diffMinutes < 60) return `${diffMinutes} minute${diffMinutes === 1 ? "" : "s"} ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours} hour${diffHours === 1 ? "" : "s"} ago`;
  const diffDays = Math.round(diffHours / 24);
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 30) return `${diffDays} days ago`;
  const diffMonths = Math.round(diffDays / 30);
  return `${diffMonths} month${diffMonths === 1 ? "" : "s"} ago`;
}

function projectStateFromStatus(status: Project["status"]): RepositoryProjectState {
  if (status === "READY") return "ready";
  if (status === "FAILED") return "failed";
  return "provisioning"; // CLONING | INDEXING
}

/**
 * Merges a raw repo from any connected provider with a matching Project
 * record (matched by repo_name === full_name) into the UI's Repository
 * shape. No matching project means the repo is launchable but not yet
 * indexed ("available").
 */
export function mapRepository(
  repo: RemoteRepository,
  provider: Repository["provider"],
  projectsByRepoName: Map<string, Project>,
): Repository {
  const [owner, ...nameParts] = repo.full_name.split("/");
  const project = projectsByRepoName.get(repo.full_name);
  const language = repo.language ?? "Unknown";

  return {
    id: `${provider}:${repo.id}`,
    owner: owner ?? repo.owner_login ?? "",
    name: nameParts.join("/") || repo.name,
    visibility: repo.private ? "private" : "public",
    ownership: repo.owner_type === "Organization" ? "organization" : "personal",
    defaultBranch: repo.default_branch,
    htmlUrl: repo.html_url,
    language,
    languageTone: languageTone(language),
    lastPushedLabel: formatRelativeTime(repo.pushed_at) ?? "Unknown",
    projectState: project ? projectStateFromStatus(project.status) : "available",
    lastIndexedLabel:
      project && project.status === "READY" ? formatRelativeTime(project.updated_at) : null,
    workspaceId: project ? project.id : null,
    provider,
  };
}
