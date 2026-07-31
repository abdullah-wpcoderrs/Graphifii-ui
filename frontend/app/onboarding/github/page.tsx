import type { Metadata } from "next";
import { OnboardingScreen } from "../../components/onboarding-screen";
import { getOnboardingState } from "../../lib/onboarding";

export const metadata: Metadata = {
  title: "Connect GitHub — Graphify",
  description:
    "Install the Graphify GitHub App and choose repository access.",
};

type GitHubOnboardingPageProps = {
  searchParams: Promise<{
    state?: string | string[];
  }>;
};

export default async function GitHubOnboardingPage({
  searchParams,
}: GitHubOnboardingPageProps) {
  const params = await searchParams;

  return <OnboardingScreen content={getOnboardingState(params.state)} />;
}
