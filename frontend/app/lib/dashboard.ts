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
  language: string;
  languageTone: "blue" | "purple" | "amber" | "cyan";
  lastPushedLabel: string;
  projectState: RepositoryProjectState;
  lastIndexedLabel: string | null;
  workspaceId: string | null;
};

export type DashboardView =
  | "list"
  | "no-installation"
  | "no-repositories"
  | "syncing"
  | "error"
  | "rate-limited";

export type DashboardFilters = {
  query: string;
  ownership: "all" | RepositoryOwnership;
  state: "all" | RepositoryProjectState;
};

export const REPOSITORIES: Repository[] = [
  {
    id: "repo_graphify",
    owner: "Graphify-Labs",
    name: "graphify",
    visibility: "public",
    ownership: "organization",
    defaultBranch: "main",
    language: "Python",
    languageTone: "blue",
    lastPushedLabel: "18 minutes ago",
    projectState: "ready",
    lastIndexedLabel: "12 minutes ago",
    workspaceId: "project_graphify",
  },
  {
    id: "repo_cloud",
    owner: "Graphify-Labs",
    name: "cloud-orchestrator",
    visibility: "private",
    ownership: "organization",
    defaultBranch: "main",
    language: "TypeScript",
    languageTone: "purple",
    lastPushedLabel: "2 hours ago",
    projectState: "provisioning",
    lastIndexedLabel: null,
    workspaceId: "project_cloud",
  },
  {
    id: "repo_docs",
    owner: "Graphify-Labs",
    name: "developer-docs",
    visibility: "private",
    ownership: "organization",
    defaultBranch: "main",
    language: "MDX",
    languageTone: "amber",
    lastPushedLabel: "Yesterday",
    projectState: "failed",
    lastIndexedLabel: "3 days ago",
    workspaceId: "project_docs",
  },
  {
    id: "repo_portfolio",
    owner: "maya-chen",
    name: "portfolio",
    visibility: "public",
    ownership: "personal",
    defaultBranch: "main",
    language: "TypeScript",
    languageTone: "purple",
    lastPushedLabel: "4 days ago",
    projectState: "available",
    lastIndexedLabel: null,
    workspaceId: null,
  },
  {
    id: "repo_api",
    owner: "maya-chen",
    name: "field-notes-api",
    visibility: "private",
    ownership: "personal",
    defaultBranch: "trunk",
    language: "Go",
    languageTone: "cyan",
    lastPushedLabel: "2 weeks ago",
    projectState: "ready",
    lastIndexedLabel: "2 weeks ago",
    workspaceId: "project_field_notes",
  },
];

const OWNERSHIP_FILTERS = new Set<DashboardFilters["ownership"]>([
  "all",
  "personal",
  "organization",
]);

const STATE_FILTERS = new Set<DashboardFilters["state"]>([
  "all",
  "available",
  "provisioning",
  "ready",
  "failed",
]);

const DASHBOARD_VIEWS = new Set<DashboardView>([
  "list",
  "no-installation",
  "no-repositories",
  "syncing",
  "error",
  "rate-limited",
]);

function firstValue(value: string | string[] | undefined) {
  return Array.isArray(value) ? value[0] : value;
}

export function getDashboardFilters(params: {
  q?: string | string[];
  ownership?: string | string[];
  state?: string | string[];
}): DashboardFilters {
  const ownership = firstValue(params.ownership);
  const state = firstValue(params.state);

  return {
    query: (firstValue(params.q) ?? "").trim().slice(0, 120),
    ownership: OWNERSHIP_FILTERS.has(
      ownership as DashboardFilters["ownership"],
    )
      ? (ownership as DashboardFilters["ownership"])
      : "all",
    state: STATE_FILTERS.has(state as DashboardFilters["state"])
      ? (state as DashboardFilters["state"])
      : "all",
  };
}

export function getDashboardView(
  value: string | string[] | undefined,
): DashboardView {
  const view = firstValue(value);
  return DASHBOARD_VIEWS.has(view as DashboardView)
    ? (view as DashboardView)
    : "list";
}

export function filterRepositories(
  repositories: Repository[],
  filters: DashboardFilters,
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
