import type { Project, ProjectStatus } from "./api";
import { formatRelativeTime } from "./repositories";

export type DashboardProject = {
  id: string;
  owner: string;
  name: string;
  status: ProjectStatus;
  updatedLabel: string;
};

const STATUS_LABELS: Record<ProjectStatus, string> = {
  CLONING: "Cloning",
  INDEXING: "Indexing",
  READY: "Ready",
  FAILED: "Failed",
};

const STATUS_TONES: Record<ProjectStatus, "ready" | "provisioning" | "failed"> = {
  CLONING: "provisioning",
  INDEXING: "provisioning",
  READY: "ready",
  FAILED: "failed",
};

export function statusLabel(status: ProjectStatus): string {
  return STATUS_LABELS[status];
}

export function statusTone(status: ProjectStatus): "ready" | "provisioning" | "failed" {
  return STATUS_TONES[status];
}

/** Projects arrive newest-first from the API; this just reshapes each row for the UI. */
export function mapProject(project: Project): DashboardProject {
  const [owner, ...nameParts] = project.repo_name.split("/");

  return {
    id: project.id,
    owner: owner ?? "",
    name: nameParts.join("/") || project.repo_name,
    status: project.status,
    updatedLabel: formatRelativeTime(project.updated_at) ?? "Unknown",
  };
}
