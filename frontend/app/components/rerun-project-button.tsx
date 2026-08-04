"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { launchProject, type LaunchProjectInput } from "../lib/api";

function RefreshIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <path d="M15.5 6.5A6 6 0 0 0 4.6 8" />
      <path d="M4.5 13.5A6 6 0 0 0 15.4 12" />
      <path d="M4 4.5v3.5h3.5" />
      <path d="M16 15.5V12h-3.5" />
    </svg>
  );
}

type RerunProjectButtonProps = {
  project: LaunchProjectInput;
  className?: string;
  label?: string;
  /** Render as an icon-only button (with a hover tooltip) instead of text. */
  renderIcon?: boolean;
  tooltip?: string;
};

export function RerunProjectButton({
  project,
  className = "repository-action",
  label = "Rerun extraction",
  renderIcon = false,
  tooltip = "Rerun extraction",
}: RerunProjectButtonProps) {
  const router = useRouter();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleRerun() {
    setError(null);
    setStarting(true);

    try {
      const result = await launchProject(project);
      router.push(`/projects/${result.project_id}/launch`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not restart extraction");
      setStarting(false);
    }
  }

  return (
    <div className="rerun-project-action">
      <button
        className={className}
        type="button"
        disabled={starting}
        onClick={handleRerun}
        aria-label={renderIcon ? (starting ? "Starting extraction…" : tooltip) : undefined}
        data-tooltip={renderIcon ? (starting ? "Starting…" : tooltip) : undefined}
      >
        {renderIcon ? <RefreshIcon /> : starting ? "Starting…" : label}
      </button>
      {error && (
        <span className="repository-action-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
