"use client";

import dynamic from "next/dynamic";
import { FormEvent, useState } from "react";
import type { AgentChange } from "../lib/api";
import { Button } from "./ui";

const MonacoDiffEditor = dynamic(
  () => import("@monaco-editor/react").then((module) => module.DiffEditor),
  {
    ssr: false,
    loading: () => (
      <div className="workspace-module-loading" role="status">
        Loading diff…
      </div>
    ),
  },
);

type AgentDiffDialogProps = {
  changes: AgentChange[];
  repoName: string;
  defaultBranch: string;
  changeRequestNoun: "pull request" | "merge request";
  onSaveEdit: (changeId: string, afterContent: string) => Promise<void>;
  onDismiss: (changeId: string) => Promise<void>;
  onDispatch: (input: { title: string; body: string; changeIds: string[] }) => Promise<void>;
  onClose: () => void;
};

function languageForPath(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase();
  const map: Record<string, string> = {
    py: "python",
    ts: "typescript",
    tsx: "typescript",
    js: "javascript",
    jsx: "javascript",
    json: "json",
    md: "markdown",
    css: "css",
    html: "html",
    yaml: "yaml",
    yml: "yaml",
  };
  return map[ext ?? ""] ?? "plaintext";
}

export function AgentDiffDialog({
  changes,
  repoName,
  defaultBranch,
  changeRequestNoun,
  onSaveEdit,
  onDismiss,
  onDispatch,
  onClose,
}: AgentDiffDialogProps) {
  const [activePath, setActivePath] = useState(changes[0]?.path ?? "");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savingPath, setSavingPath] = useState<string | null>(null);
  const [dismissingPath, setDismissingPath] = useState<string | null>(null);
  const [title, setTitle] = useState(`Graphify: proposed changes to ${repoName.split("/").pop()}`);
  const [body, setBody] = useState(
    "Changes proposed by the Graphify agent. Reviewed and edited before submission.",
  );
  const [dispatching, setDispatching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const active = changes.find((change) => change.path === activePath) ?? changes[0] ?? null;
  const activeDraft = active ? (drafts[active.id] ?? active.after_content) : "";
  const dirty = active ? activeDraft !== active.after_content : false;

  async function handleSave() {
    if (!active) return;
    setSavingPath(active.path);
    setError(null);
    try {
      await onSaveEdit(active.id, activeDraft);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the edit");
    } finally {
      setSavingPath(null);
    }
  }

  async function handleDismiss(change: AgentChange) {
    setDismissingPath(change.path);
    setError(null);
    try {
      await onDismiss(change.id);
      if (activePath === change.path) {
        const remaining = changes.filter((c) => c.id !== change.id);
        setActivePath(remaining[0]?.path ?? "");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not dismiss the change");
    } finally {
      setDismissingPath(null);
    }
  }

  async function handleDispatch(event: FormEvent) {
    event.preventDefault();
    if (!confirming) {
      setConfirming(true);
      return;
    }
    setDispatching(true);
    setError(null);
    try {
      await onDispatch({ title: title.trim(), body: body.trim(), changeIds: changes.map((c) => c.id) });
    } catch (err) {
      setError(err instanceof Error ? err.message : `Could not open the ${changeRequestNoun}`);
      setDispatching(false);
      setConfirming(false);
      return;
    }
    setDispatching(false);
  }

  if (changes.length === 0) {
    return null;
  }

  return (
    <div className="modal-scrim" role="presentation" onClick={onClose}>
      <div
        className="modal-panel diff-dialog-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="agent-diff-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="agent-diff-title">Review proposed changes</h2>
        <p className="diff-dialog-subtitle">
          {changes.length} file{changes.length === 1 ? "" : "s"} · will open a {changeRequestNoun} against{" "}
          <strong>{defaultBranch}</strong> in <strong>{repoName}</strong>
        </p>

        <div className="diff-dialog-body">
          <ul className="diff-dialog-file-list">
            {changes.map((change) => (
              <li key={change.id}>
                <button
                  type="button"
                  className={change.path === activePath ? "is-active" : ""}
                  onClick={() => setActivePath(change.path)}
                >
                  <span>{change.path}</span>
                  {change.is_new_file && <i>new</i>}
                  {change.edited_by_user && <i>edited</i>}
                </button>
                <button
                  type="button"
                  aria-label={`Dismiss change to ${change.path}`}
                  className="diff-dialog-dismiss"
                  disabled={dismissingPath === change.path}
                  onClick={() => handleDismiss(change)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>

          <div className="diff-dialog-editor">
            {active && (
              <>
                <MonacoDiffEditor
                  language={languageForPath(active.path)}
                  original={active.before_content ?? ""}
                  modified={activeDraft}
                  theme="vs-dark"
                  onMount={(editor) => {
                    const modifiedModel = editor.getModifiedEditor();
                    modifiedModel.onDidChangeModelContent(() => {
                      setDrafts((current) => ({
                        ...current,
                        [active.id]: modifiedModel.getValue(),
                      }));
                    });
                  }}
                  options={{
                    readOnly: false,
                    originalEditable: false,
                    renderSideBySide: true,
                    minimap: { enabled: false },
                    fontSize: 12,
                    scrollBeyondLastLine: false,
                  }}
                  height="100%"
                />
                <div className="diff-dialog-editor-footer">
                  <span>{dirty ? "Unsaved edit" : "Matches the agent's proposal"}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={!dirty}
                    loading={savingPath === active.path}
                    onClick={handleSave}
                  >
                    Save edit
                  </Button>
                </div>
              </>
            )}
          </div>
        </div>

        <form onSubmit={handleDispatch} className="diff-dialog-pr-form">
          <label>
            <span>Title</span>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              required
              maxLength={255}
            />
          </label>
          <label>
            <span>Description</span>
            <textarea value={body} onChange={(event) => setBody(event.target.value)} rows={3} />
          </label>

          {error && (
            <p className="modal-error" role="alert">
              {error}
            </p>
          )}

          <div className="modal-actions">
            <Button type="button" variant="ghost" onClick={onClose}>
              Close
            </Button>
            <Button type="submit" variant="primary" loading={dispatching} disabled={!title.trim()}>
              {confirming ? `Confirm: open ${changeRequestNoun}` : `Open ${changeRequestNoun}`}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
