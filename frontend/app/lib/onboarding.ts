export type OnboardingState =
  | "not-installed"
  | "no-repositories"
  | "connected"
  | "pending"
  | "suspended"
  | "removed";

export type OnboardingContent = {
  state: OnboardingState;
  statusLabel: string;
  statusTone: "neutral" | "success" | "warning" | "danger";
  eyebrow: string;
  title: string;
  description: string;
  primaryLabel: string;
  primaryHref: string;
  secondaryLabel?: string;
  secondaryHref?: string;
  repositoryCount: number | null;
  installationOwner: string | null;
  notice: string;
};

const ONBOARDING_STATES: Record<OnboardingState, OnboardingContent> = {
  "not-installed": {
    state: "not-installed",
    statusLabel: "Installation required",
    statusTone: "neutral",
    eyebrow: "GITHUB APP SETUP",
    title: "Choose which repositories Graphify can access.",
    description:
      "Install the Graphify GitHub App, then select only the personal or organization repositories you want available in your workspace.",
    primaryLabel: "Install Graphify GitHub App",
    primaryHref: "/onboarding/github?state=no-repositories",
    repositoryCount: null,
    installationOwner: null,
    notice:
      "Graphify never requests access to repositories outside the GitHub App installation you approve.",
  },
  "no-repositories": {
    state: "no-repositories",
    statusLabel: "No repositories selected",
    statusTone: "warning",
    eyebrow: "REPOSITORY ACCESS",
    title: "The GitHub App is installed. Select a repository to continue.",
    description:
      "The installation is active, but Graphify does not currently have access to any repositories.",
    primaryLabel: "Configure repository access",
    primaryHref: "/onboarding/github?state=connected",
    secondaryLabel: "Review installation",
    secondaryHref: "/onboarding/github?state=not-installed",
    repositoryCount: 0,
    installationOwner: "Graphify Labs",
    notice:
      "Select at least one repository in GitHub. You can change this list at any time.",
  },
  connected: {
    state: "connected",
    statusLabel: "Connected",
    statusTone: "success",
    eyebrow: "SETUP COMPLETE",
    title: "Your GitHub repositories are ready for Graphify.",
    description:
      "The installation is healthy and repository access has been confirmed. You can now continue to your project dashboard.",
    primaryLabel: "Continue to dashboard",
    primaryHref: "/dashboard",
    secondaryLabel: "Change repository access",
    secondaryHref: "/onboarding/github?state=no-repositories",
    repositoryCount: 12,
    installationOwner: "Graphify Labs",
    notice:
      "Repository content is accessed only when you launch or resume a Graphify workspace.",
  },
  pending: {
    state: "pending",
    statusLabel: "Organization approval pending",
    statusTone: "warning",
    eyebrow: "AWAITING APPROVAL",
    title: "An organization owner needs to approve Graphify.",
    description:
      "Your installation request was sent successfully. Repository access remains unavailable until a GitHub organization owner approves it.",
    primaryLabel: "Check approval again",
    primaryHref: "/onboarding/github?state=pending",
    secondaryLabel: "Use a different installation",
    secondaryHref: "/onboarding/github?state=not-installed",
    repositoryCount: null,
    installationOwner: "Acme Engineering",
    notice:
      "You can safely leave this page and return after the organization owner approves the request.",
  },
  suspended: {
    state: "suspended",
    statusLabel: "Installation suspended",
    statusTone: "danger",
    eyebrow: "ACTION REQUIRED",
    title: "Graphify can no longer access this installation.",
    description:
      "A GitHub owner suspended the installation. Existing Graphify projects are preserved, but repository sync and workspace launches are paused.",
    primaryLabel: "Repair GitHub access",
    primaryHref: "/onboarding/github?state=connected",
    secondaryLabel: "Choose another installation",
    secondaryHref: "/onboarding/github?state=not-installed",
    repositoryCount: 12,
    installationOwner: "Graphify Labs",
    notice:
      "Only a GitHub installation owner can restore access to suspended repositories.",
  },
  removed: {
    state: "removed",
    statusLabel: "Installation removed",
    statusTone: "danger",
    eyebrow: "RECONNECT GITHUB",
    title: "The GitHub App installation was removed.",
    description:
      "Graphify no longer has repository access. Your project records are preserved, but new sync and workspace actions are unavailable.",
    primaryLabel: "Install Graphify again",
    primaryHref: "/onboarding/github?state=no-repositories",
    secondaryLabel: "Return to sign in",
    secondaryHref: "/",
    repositoryCount: 0,
    installationOwner: null,
    notice:
      "Reinstalling the app does not automatically restore access to repositories you do not select.",
  },
};

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export function getOnboardingState(
  value: string | string[] | undefined,
): OnboardingContent {
  const candidate = firstValue(value);

  if (candidate && candidate in ONBOARDING_STATES) {
    return ONBOARDING_STATES[candidate as OnboardingState];
  }

  return ONBOARDING_STATES["not-installed"];
}
