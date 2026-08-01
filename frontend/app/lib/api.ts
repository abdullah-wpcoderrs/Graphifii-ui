import { apiDelete, apiGet, apiPost, apiPut } from "./api-client";

export type ProjectStatus = "CLONING" | "INDEXING" | "READY" | "FAILED";

export type Project = {
  id: string;
  repo_name: string;
  repo_url: string;
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
