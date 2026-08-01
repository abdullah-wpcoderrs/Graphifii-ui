import type { Metadata } from "next";
import { DashboardScreen } from "../components/dashboard-screen";
import {
  filterRepositories,
  getDashboardFilters,
  getDashboardView,
  REPOSITORIES,
} from "../lib/dashboard";

export const metadata: Metadata = {
  title: "Repositories — Graphify",
  description:
    "Search your GitHub repositories and launch or resume a Graphify workspace.",
};

type DashboardPageProps = {
  searchParams: Promise<{
    q?: string | string[];
    ownership?: string | string[];
    state?: string | string[];
    view?: string | string[];
  }>;
};

export default async function DashboardPage({
  searchParams,
}: DashboardPageProps) {
  const params = await searchParams;
  const filters = getDashboardFilters(params);
  const repositories = filterRepositories(REPOSITORIES, filters);

  return (
    <DashboardScreen
      filters={filters}
      repositories={repositories}
      totalRepositoryCount={REPOSITORIES.length}
      totalWorkspaceCount={
        REPOSITORIES.filter((repository) => repository.workspaceId).length
      }
      view={getDashboardView(params.view)}
    />
  );
}
