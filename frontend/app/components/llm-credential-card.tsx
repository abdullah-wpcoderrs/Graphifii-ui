"use client";

import { useState } from "react";
import type { AdminCredential, LLMProvider } from "../lib/api";
import { verifyAdminCredential } from "../lib/api";
import { Badge, Button } from "./ui";

const PROVIDER_LABELS: Record<LLMProvider, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic (Claude)",
  gemini: "Gemini",
};

type LLMCredentialCardProps = {
  provider: LLMProvider;
  credential: AdminCredential | undefined;
  onConfigure: () => void;
  onDelete: () => void;
};

export function LLMCredentialCard({
  provider,
  credential,
  onConfigure,
  onDelete,
}: LLMCredentialCardProps) {
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<{ ok: boolean; message: string } | null>(null);
  const configured = credential?.configured ?? false;

  async function handleVerify() {
    setVerifying(true);
    setVerifyResult(null);
    try {
      const result = await verifyAdminCredential(provider);
      setVerifyResult({
        ok: result.ok,
        message: result.ok ? `Connected — ${result.model}` : result.error || "Verification failed",
      });
    } catch (err) {
      setVerifyResult({ ok: false, message: err instanceof Error ? err.message : "Verification failed" });
    } finally {
      setVerifying(false);
    }
  }

  return (
    <article className="llm-credential-card">
      <div className="llm-credential-card-header">
        <strong>{PROVIDER_LABELS[provider]}</strong>
        <Badge tone={configured ? "success" : "neutral"}>
          {configured ? "Configured" : "Not configured"}
        </Badge>
      </div>

      {configured && credential?.model && (
        <p className="llm-credential-card-model">{credential.model}</p>
      )}

      {configured && verifyResult && (
        <p className={`llm-credential-card-verify ${verifyResult.ok ? "is-ok" : "is-error"}`}>
          {verifyResult.message}
        </p>
      )}

      <div className="llm-credential-card-actions">
        <Button variant="primary" size="sm" onClick={onConfigure}>
          {configured ? "Edit" : "Configure"}
        </Button>
        {configured && (
          <>
            <Button variant="secondary" size="sm" onClick={handleVerify} loading={verifying}>
              Test Connection
            </Button>
            <Button variant="danger" size="sm" onClick={onDelete}>
              Delete
            </Button>
          </>
        )}
      </div>
    </article>
  );
}
