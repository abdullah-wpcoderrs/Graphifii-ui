import type { Metadata } from "next";
import { WorkspaceShell } from "../../components/workspace-shell";

export const metadata: Metadata = {
  title: "Graphify workspace",
  description:
    "Inspect code, architecture, and graph-aware agent changes in one workspace.",
};

type WorkspacePageProps = {
  params: Promise<{ projectId: string }>;
};

export default async function WorkspacePage({ params }: WorkspacePageProps) {
  const { projectId } = await params;
  return <WorkspaceShell projectId={projectId} />;
}
