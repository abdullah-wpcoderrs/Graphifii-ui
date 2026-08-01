"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AdminCredential,
  deleteAdminCredential,
  fetchAdminCredentials,
  LLMProvider,
  saveAdminCredential,
  updateAdminCredential,
} from "../../../lib/api";
import { LLMCredentialCard } from "../../../components/llm-credential-card";
import { LLMCredentialModal } from "../../../components/llm-credential-modal";
import { ErrorState, Spinner } from "../../../components/ui";

const PROVIDERS: LLMProvider[] = ["openai", "anthropic", "gemini"];

export default function AdminSettingsPage() {
  const [credentials, setCredentials] = useState<Record<string, AdminCredential> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedProvider, setSelectedProvider] = useState<LLMProvider | null>(null);

  const load = useCallback(() => {
    setError(null);
    fetchAdminCredentials()
      .then((data) => setCredentials(Object.fromEntries(data.map((c) => [c.provider, c]))))
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load credentials"));
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial data load on mount, not a synchronous render-time update
    load();
  }, [load]);

  async function handleSave(provider: LLMProvider, apiKey: string, model: string) {
    const existing = credentials?.[provider]?.configured;
    if (existing) {
      await updateAdminCredential(provider, apiKey, model);
    } else {
      await saveAdminCredential(provider, apiKey, model);
    }
    setSelectedProvider(null);
    load();
  }

  async function handleDelete(provider: LLMProvider) {
    await deleteAdminCredential(provider);
    load();
  }

  if (error) {
    return (
      <div className="page-content">
        <ErrorState title="Could not load admin settings" description={error} onRetry={load} />
      </div>
    );
  }

  if (!credentials) {
    return (
      <div className="page-content page-content-centered">
        <Spinner size="lg" label="Loading admin settings" />
      </div>
    );
  }

  return (
    <div className="page-content">
      <header className="page-header">
        <h1>Admin Settings</h1>
        <p>Configure the LLM providers Graphify uses for graph extraction.</p>
      </header>

      <section className="admin-credentials-grid">
        {PROVIDERS.map((provider) => (
          <LLMCredentialCard
            key={provider}
            provider={provider}
            credential={credentials[provider]}
            onConfigure={() => setSelectedProvider(provider)}
            onDelete={() => handleDelete(provider)}
          />
        ))}
      </section>

      {selectedProvider && (
        <LLMCredentialModal
          provider={selectedProvider}
          currentModel={credentials[selectedProvider]?.model ?? null}
          onSave={(apiKey, model) => handleSave(selectedProvider, apiKey, model)}
          onClose={() => setSelectedProvider(null)}
        />
      )}
    </div>
  );
}
