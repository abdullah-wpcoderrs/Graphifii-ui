"use client";

import { FormEvent, useState } from "react";
import type { LLMProvider } from "../lib/api";
import { Button, Input } from "./ui";

const PROVIDER_LABELS: Record<LLMProvider, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic (Claude)",
  gemini: "Gemini",
};

const PROVIDER_MODEL_PLACEHOLDERS: Record<LLMProvider, string> = {
  openai: "gpt-4.1-mini",
  anthropic: "claude-sonnet-4-6",
  gemini: "gemini-3-flash-preview",
};

type LLMCredentialModalProps = {
  provider: LLMProvider;
  currentModel: string | null;
  onSave: (apiKey: string, model: string) => Promise<void>;
  onClose: () => void;
};

export function LLMCredentialModal({
  provider,
  currentModel,
  onSave,
  onClose,
}: LLMCredentialModalProps) {
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(currentModel ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!apiKey.trim()) {
      setError("API key is required");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave(apiKey.trim(), model.trim() || PROVIDER_MODEL_PLACEHOLDERS[provider]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save credential");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-scrim" role="presentation" onClick={onClose}>
      <div
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="llm-modal-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="llm-modal-title">Configure {PROVIDER_LABELS[provider]}</h2>
        <form onSubmit={handleSubmit}>
          <Input
            label="API Key"
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder="Enter your API key"
            autoComplete="off"
            autoFocus
          />
          <Input
            label="Model"
            value={model}
            onChange={(event) => setModel(event.target.value)}
            placeholder={PROVIDER_MODEL_PLACEHOLDERS[provider]}
            hint="Leave blank to use the default model"
          />
          {error && (
            <p className="modal-error" role="alert">
              {error}
            </p>
          )}
          <div className="modal-actions">
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={saving}>
              Save
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
