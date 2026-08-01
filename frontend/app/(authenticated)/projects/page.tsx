import type { Metadata } from "next";
import { ProjectsQueryScreen } from "../../components/projects-query-screen";

export const metadata: Metadata = {
  title: "Projects — Graphify",
  description: "Ask questions about a graphed codebase.",
};

export default function ProjectsPage() {
  return <ProjectsQueryScreen />;
}
