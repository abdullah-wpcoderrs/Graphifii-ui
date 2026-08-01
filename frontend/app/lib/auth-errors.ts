export type AuthErrorCode =
  | "access_denied"
  | "invalid_state"
  | "github_unavailable"
  | "callback_failed"
  | "integration_connection_failed"
  | "unknown";

export type AuthErrorContent = {
  code: AuthErrorCode;
  eyebrow: string;
  title: string;
  description: string;
  guidance: string;
};

const AUTH_ERRORS: Record<AuthErrorCode, AuthErrorContent> = {
  access_denied: {
    code: "access_denied",
    eyebrow: "AUTHORIZATION CANCELED",
    title: "GitHub access was not granted.",
    description:
      "No account or repository access was changed. Graphify can only continue after you approve the GitHub authorization request.",
    guidance:
      "Try again when you are ready. You will be able to review the requested permissions before approving.",
  },
  invalid_state: {
    code: "invalid_state",
    eyebrow: "SESSION EXPIRED",
    title: "This sign-in attempt is no longer valid.",
    description:
      "The authorization window may have been open too long, or the sign-in request was already used.",
    guidance:
      "Return to the sign-in screen and begin a new GitHub authorization request.",
  },
  github_unavailable: {
    code: "github_unavailable",
    eyebrow: "GITHUB UNAVAILABLE",
    title: "GitHub could not complete the connection.",
    description:
      "GitHub or the Graphify GitHub App is temporarily unavailable. Your existing permissions have not changed.",
    guidance:
      "Wait a moment and retry. If the issue continues, check GitHub service status before trying again.",
  },
  callback_failed: {
    code: "callback_failed",
    eyebrow: "CONNECTION INTERRUPTED",
    title: "Graphify could not finish signing you in.",
    description:
      "The authorization response reached Graphify, but the secure session could not be completed.",
    guidance:
      "Retry the connection. Share the reference below with your administrator if the problem repeats.",
  },
  integration_connection_failed: {
    code: "integration_connection_failed",
    eyebrow: "INTEGRATION CONNECTION FAILED",
    title: "Could not connect to the integration provider.",
    description:
      "The authorization request may have expired, or the provider was temporarily unavailable. Your existing integrations and repository access are unchanged.",
    guidance:
      "Return to Integrations and try connecting again. Share the reference below with your administrator if the problem repeats.",
  },
  unknown: {
    code: "unknown",
    eyebrow: "SIGN-IN ERROR",
    title: "Something interrupted the GitHub connection.",
    description:
      "Graphify could not complete this sign-in attempt. No repository permissions were changed.",
    guidance:
      "Start a new sign-in attempt. If the problem repeats, share the safe reference below with your administrator.",
  },
};

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export function getAuthError(
  value: string | string[] | undefined,
): AuthErrorContent {
  const candidate = firstValue(value);

  if (candidate && candidate in AUTH_ERRORS) {
    return AUTH_ERRORS[candidate as AuthErrorCode];
  }

  return AUTH_ERRORS.unknown;
}

export function getSafeReference(
  value: string | string[] | undefined,
): string | null {
  const candidate = firstValue(value);

  if (!candidate || !/^[A-Za-z0-9_-]{4,64}$/.test(candidate)) {
    return null;
  }

  return candidate;
}
