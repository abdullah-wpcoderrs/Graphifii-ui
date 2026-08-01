"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  AdminCredential,
  AgentBudget,
  deleteAdminCredential,
  fetchAdminCredentials,
  fetchAgentBudget,
  LLMProvider,
  saveAdminCredential,
  updateAdminCredential,
  updateAgentBudget,
} from "../../../lib/api";
import { LLMCredentialCard } from "../../../components/llm-credential-card";
import { LLMCredentialModal } from "../../../components/llm-credential-modal";
import { Button, ErrorState, Input, Spinner } from "../../../components/ui";

const PROVIDERS: LLMProvider[] = ["openai", "anthropic", "gemini"];

function AgentBudgetSettings() {
  const [budget, setBudget] = useState<AgentBudget | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(() => {
    fetchAgentBudget()
      .then((data) => {
        setBudget(data);
        setDraft(data.unlimited ? "-1" : data.daily_budget_usd);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load the agent budget"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await updateAgentBudget(draft.trim());
      setSaved(true);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the agent budget");
    } finally {
      setSaving(false);
    }
  }

  if (!budget) {
    return (
      <section className="admin-budget-card">
        <Spinner size="sm" label="Loading agent budget" />
      </section>
    );
  }

  return (
    <section className="admin-budget-card">
      <h2>Agent daily spend limit</h2>
      <p>
        Maximum AI spend per user per day for agent conversations (question answering and proposed
        code changes). Resets at 00:00 UTC. Set to <code>-1</code> to disable the cap.
      </p>
      <form onSubmit={handleSubmit}>
        <Input
          label="Daily budget (USD per user)"
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
            setSaved(false);
          }}
          placeholder={budget.default}
          hint={budget.unlimited ? "Currently unlimited" : `Currently $${budget.daily_budget_usd}/day`}
        />
        {error && (
          <p className="modal-error" role="alert">
            {error}
          </p>
        )}
        <div className="admin-budget-actions">
          {saved && <span className="admin-budget-saved">Saved</span>}
          <Button type="submit" variant="primary" loading={saving}>
            Save
          </Button>
        </div>
      </form>
    </section>
  );
}

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

      <AgentBudgetSettings />

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
