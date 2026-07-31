import type { Metadata } from "next";
import { RecoveryScreen } from "../../components/recovery-screen";
import { getAuthError, getSafeReference } from "../../lib/auth-errors";

export const metadata: Metadata = {
  title: "Sign-in error — Graphify",
  description: "Recover from an interrupted Graphify GitHub connection.",
};

type AuthErrorPageProps = {
  searchParams: Promise<{
    code?: string | string[];
    error?: string | string[];
    ref?: string | string[];
  }>;
};

export default async function AuthErrorPage({
  searchParams,
}: AuthErrorPageProps) {
  const params = await searchParams;
  const error = getAuthError(params.code ?? params.error);
  const reference = getSafeReference(params.ref);

  return (
    <RecoveryScreen
      code="AUTH"
      eyebrow={error.eyebrow}
      title={error.title}
      description={error.description}
      guidance={error.guidance}
      reference={reference}
      primaryLabel="Retry with GitHub"
      primaryHref="/"
      secondaryLabel="Return to sign in"
      secondaryHref="/"
    />
  );
}
