"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  disconnectIntegration,
  fetchIntegrations,
  Integration,
  integrationLoginUrl,
} from "../../lib/api";
import { getPublicApiUrl } from "../../lib/env";
import { IntegrationCard } from "../../components/integration-card";
import { ErrorState, Spinner } from "../../components/ui";

export default function IntegrationsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [integrations, setIntegrations] = useState<Integration[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    fetchIntegrations()
      .then(setIntegrations)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load integrations"));
  }, []);

  const callbackStatus = searchParams.get("status");
  const callbackProvider = searchParams.get("provider");

  useEffect(() => {
    if (callbackStatus) {
      // Clear the query params after reading them once, so a refresh
      // doesn't re-show the "connected" banner.
      router.replace("/integrations");
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial data load on mount, not a synchronous render-time update
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only re-run when the OAuth callback params change, not on every load() identity change
  }, [callbackStatus, callbackProvider, router]);

  async function handleConnect(provider: "gitlab" | "gitbucket") {
    const apiUrl = getPublicApiUrl();
    if (!apiUrl) return;
    window.location.assign(integrationLoginUrl(provider, apiUrl));
  }

  async function handleDisconnect(provider: "gitlab" | "gitbucket") {
    setDisconnectingId(provider);
    try {
      await disconnectIntegration(provider);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disconnect");
    } finally {
      setDisconnectingId(null);
    }
  }

  if (error) {
    return (
      <div className="page-content">
        <ErrorState title="Could not load integrations" description={error} onRetry={load} />
      </div>
    );
  }

  if (!integrations) {
    return (
      <div className="page-content page-content-centered">
        <Spinner size="lg" label="Loading integrations" />
      </div>
    );
  }

  return (
    <div className="page-content">
      <header className="page-header">
        <h1>Integrations</h1>
        <p>Connect the source providers Graphify can pull repositories from.</p>
      </header>

      {callbackStatus === "success" && (
        <div className="page-banner is-success" role="status">
          {callbackProvider ? `${callbackProvider} connected successfully.` : "Connected successfully."}
        </div>
      )}

      <div className="integrations-grid">
        {integrations.map((integration) => (
          <IntegrationCard
            key={integration.id}
            integration={integration}
            disconnecting={disconnectingId === integration.id}
            onConnect={() => handleConnect(integration.id as "gitlab" | "gitbucket")}
            onDisconnect={() => handleDisconnect(integration.id as "gitlab" | "gitbucket")}
          />
        ))}
      </div>
    </div>
  );
}
