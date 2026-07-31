import type { Metadata } from "next";
import { RecoveryScreen } from "./components/recovery-screen";

export const metadata: Metadata = {
  title: "Page not found — Graphify",
  description: "The requested Graphify page could not be found.",
};

export default function NotFound() {
  return (
    <RecoveryScreen
      code="404"
      eyebrow="PAGE NOT FOUND"
      title="This route is not part of the graph."
      description="The page may have moved, the URL may be incomplete, or this workspace route no longer exists."
      guidance="Return to the Graphify sign-in screen and continue from a known route."
      primaryLabel="Return to Graphify"
      primaryHref="/"
      secondaryLabel="Try signing in"
      secondaryHref="/"
    />
  );
}
