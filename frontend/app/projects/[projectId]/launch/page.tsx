import type { Metadata } from "next";
import { ProvisioningScreen } from "../../../components/provisioning-screen";

export const metadata: Metadata = {
  title: "Preparing workspace — Graphify",
  description:
    "Provision a sandbox and build the repository architecture graph.",
};

type ProjectLaunchPageProps = {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ state?: string | string[] }>;
};

export default async function ProjectLaunchPage({
  params,
  searchParams,
}: ProjectLaunchPageProps) {
  const [{ projectId }, query] = await Promise.all([params, searchParams]);
  const state = Array.isArray(query.state) ? query.state[0] : query.state;

  return (
    <ProvisioningScreen
      initialFailure={state === "failed"}
      projectId={projectId}
    />
  );
}
