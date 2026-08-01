import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from "./api-client";

export type ProjectStatus = "CLONING" | "INDEXING" | "READY" | "FAILED";

export type Project = {
  id: string;
  repo_name: string;
  repo_url: string;
  provider: IntegrationProvider;
  default_branch: string;
  status: ProjectStatus;
  graph_json_url: string | null;
  graph_html_url: string | null;
  created_at: string;
  updated_at: string;
};

export type RemoteRepository = {
  id: number;
  name: string;
  full_name: string;
  html_url: string;
  description: string | null;
  default_branch: string;
  stargazers_count?: number;
  private: boolean;
  language: string | null;
  pushed_at: string | null;
  owner_login: string | null;
  owner_type: "User" | "Organization";
};

export type IntegrationProvider = "github" | "gitlab" | "gitbucket";

export type IntegrationStatus = "connected" | "not_connected" | "not_configured";

export type Integration = {
  id: IntegrationProvider;
  name: string;
  icon: string;
  status: IntegrationStatus;
  login: string | null;
  message?: string;
};

export type LaunchProgress = {
  project_id: string;
  status: ProjectStatus;
  progress_percent: number;
  message: string | null;
  error: string | null;
  graph_json_url: string | null;
  terminal: boolean;
  updated_at: string | null;
};

export type LLMProvider = "openai" | "anthropic" | "gemini";

export type AdminCredential = {
  provider: LLMProvider;
  configured: boolean;
  model: string | null;
  updated_at: string | null;
};

// ========== Projects ==========

export function fetchProjects() {
  return apiGet<Project[]>("/api/projects");
}

export function fetchProject(id: string) {
  return apiGet<Project>(`/api/projects/${id}`);
}

export function fetchProjectGraph(id: string) {
  return apiGet<unknown>(`/api/projects/${id}/graph`);
}

export function fetchProjectFiles(id: string) {
  return apiGet<unknown>(`/api/projects/${id}/files`);
}

export type ProjectFileContent = {
  path: string;
  content: string;
  sha: string | null;
  size: number;
};

export function fetchProjectFileContent(id: string, path: string) {
  return apiGet<ProjectFileContent>(
    `/api/projects/${id}/files/${path.split("/").map(encodeURIComponent).join("/")}`,
  );
}

export function launchProject(input: {
  repoFullName: string;
  repoUrl: string;
  provider: IntegrationProvider;
  defaultBranch: string;
}) {
  return apiPost<LaunchProgress>("/api/projects", {
    repo_full_name: input.repoFullName,
    repo_url: input.repoUrl,
    provider: input.provider,
    default_branch: input.defaultBranch,
  });
}

export function cancelProject(id: string) {
  return apiPost<{ ok: true; project_id: string }>(`/api/projects/${id}/cancel`);
}

// ========== Repositories ==========

export function fetchGitHubRepos() {
  return apiGet<RemoteRepository[]>("/api/repositories");
}

export function fetchIntegrationRepos(provider: "gitlab" | "gitbucket") {
  return apiGet<RemoteRepository[]>(`/api/integrations/${provider}/repos`);
}

// ========== Integrations ==========

export function fetchIntegrations() {
  return apiGet<Integration[]>("/api/integrations");
}

export function integrationLoginUrl(provider: "gitlab" | "gitbucket", apiUrl: string) {
  return `${apiUrl}/api/integrations/${provider}/login`;
}

export function disconnectIntegration(provider: "gitlab" | "gitbucket") {
  return apiPost<{ ok: true }>(`/api/integrations/${provider}/disconnect`);
}

// ========== Admin Credentials ==========

export function fetchAdminCredentials() {
  return apiGet<AdminCredential[]>("/api/admin/credentials");
}

export function saveAdminCredential(provider: LLMProvider, apiKey: string, model?: string) {
  return apiPost<{ ok: true; provider: string }>("/api/admin/credentials", {
    provider,
    api_key: apiKey,
    model: model ?? null,
  });
}

export function updateAdminCredential(provider: LLMProvider, apiKey: string, model?: string) {
  return apiPut<{ ok: true }>(`/api/admin/credentials/${provider}`, {
    provider,
    api_key: apiKey,
    model: model ?? null,
  });
}

export function verifyAdminCredential(provider: LLMProvider) {
  return apiPost<{ ok: boolean; model?: string; error?: string }>(
    "/api/admin/credentials/verify",
    { provider },
  );
}

export function deleteAdminCredential(provider: LLMProvider) {
  return apiDelete<{ ok: true }>(`/api/admin/credentials/${provider}`);
}

// ========== Admin usage & spend ==========

export type AdminUsageTotals = {
  prompt_tokens: number;
  completion_tokens: number;
  cost_estimate: number;
  calls: number;
};

export type AdminUsageByProvider = AdminUsageTotals & { provider: string };

export type AdminUsageByUser = {
  user_id: string | null;
  github_login: string;
  cost_estimate: number;
  calls: number;
};

export type AdminUsageSummary = {
  range_days: number;
  since: string;
  totals: AdminUsageTotals;
  by_provider: AdminUsageByProvider[];
  by_user: AdminUsageByUser[];
};

export function fetchAdminUsage(days: number) {
  return apiGet<AdminUsageSummary>(`/api/admin/usage?days=${days}`);
}

// ========== Admin analytics ==========

export type AdminAnalytics = {
  range_days: number;
  since: string;
  users: {
    total: number;
    new_in_range: number;
    active_in_range: number;
  };
  projects: {
    launched_in_range: number;
    by_status: Record<string, number>;
    success_rate: number | null;
    avg_indexing_seconds: number | null;
  };
};

export function fetchAdminAnalytics(days: number) {
  return apiGet<AdminAnalytics>(`/api/admin/analytics?days=${days}`);
}

// ========== Admin user management ==========

export type AdminUserSummary = {
  id: string;
  github_login: string;
  email: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
  project_count: number;
  integrations: {
    github: boolean;
    gitlab: boolean;
    gitbucket: boolean;
  };
};

export type AdminUserList = {
  total: number;
  limit: number;
  offset: number;
  users: AdminUserSummary[];
};

export function fetchAdminUsers(limit = 100, offset = 0) {
  return apiGet<AdminUserList>(`/api/admin/users?limit=${limit}&offset=${offset}`);
}

export function updateAdminUser(id: string, isActive: boolean) {
  return apiPatch<{ ok: true; id: string; is_active: boolean }>(`/api/admin/users/${id}`, {
    is_active: isActive,
  });
}

export function deleteAdminUser(id: string) {
  return apiDelete<{ ok: true; deleted: string }>(`/api/admin/users/${id}`);
}

// ========== Agent ==========

export type AgentMessageRole = "user" | "assistant";

export type AgentMessage = {
  id: string;
  role: AgentMessageRole;
  content: string;
  error: string | null;
  created_at: string | null;
};

export type AgentChangeStatus = "PROPOSED" | "SUPERSEDED" | "DISMISSED" | "COMMITTED";

export type AgentChange = {
  id: string;
  path: string;
  before_content: string | null;
  after_content: string;
  diff: string;
  status: AgentChangeStatus;
  edited_by_user: boolean;
  is_new_file: boolean;
  updated_at: string | null;
};

export type AgentHistory = {
  session_id: string;
  messages: AgentMessage[];
  changes: AgentChange[];
};

export function fetchAgentHistory(projectId: string) {
  return apiGet<AgentHistory>(`/api/projects/${projectId}/agent/messages`);
}

export function saveAgentChange(projectId: string, changeId: string, afterContent: string) {
  return apiPut<AgentChange>(`/api/projects/${projectId}/agent/changes/${changeId}`, {
    after_content: afterContent,
  });
}

export function dismissAgentChange(projectId: string, changeId: string) {
  return apiPost<{ ok: true }>(`/api/projects/${projectId}/agent/changes/${changeId}/dismiss`);
}

export type PullRequestResult = {
  ok: true;
  number: number;
  url: string;
  branch: string;
  kind: "pull request" | "merge request";
  committed_files: string[];
  created_at: string;
};

export function createPullRequest(
  projectId: string,
  input: { title: string; body: string; changeIds: string[]; confirm: boolean },
) {
  return apiPost<PullRequestResult>(`/api/projects/${projectId}/pull-request`, {
    title: input.title,
    body: input.body,
    change_ids: input.changeIds,
    confirm: input.confirm,
  });
}

// ========== Admin: agent budget ==========

export type AgentBudget = {
  daily_budget_usd: string;
  unlimited: boolean;
  default: string;
};

export function fetchAgentBudget() {
  return apiGet<AgentBudget>("/api/admin/settings/agent-budget");
}

export function updateAgentBudget(dailyBudgetUsd: string) {
  return apiPut<{ ok: true; daily_budget_usd: string }>("/api/admin/settings/agent-budget", {
    daily_budget_usd: dailyBudgetUsd,
  });
}
