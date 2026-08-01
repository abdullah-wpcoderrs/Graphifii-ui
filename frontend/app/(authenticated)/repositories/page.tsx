import type { Metadata } from "next";
import { RepositoriesScreen } from "../../components/repositories-screen";
import { getRepositoryFilters } from "../../lib/repositories";

export const metadata: Metadata = {
  title: "Repositories — Graphify",
  description:
    "Search your connected repositories and launch or resume a Graphify workspace.",
};

type RepositoriesPageProps = {
  searchParams: Promise<{
    q?: string | string[];
    ownership?: string | string[];
    state?: string | string[];
  }>;
};

export default async function RepositoriesPage({ searchParams }: RepositoriesPageProps) {
  const params = await searchParams;
  const filters = getRepositoryFilters(params);

  return <RepositoriesScreen filters={filters} />;
}
