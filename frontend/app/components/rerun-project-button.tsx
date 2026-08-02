"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { launchProject, type LaunchProjectInput } from "../lib/api";

type RerunProjectButtonProps = {
  project: LaunchProjectInput;
  className?: string;
  label?: string;
};

export function RerunProjectButton({
  project,
  className = "repository-action",
  label = "Rerun extraction",
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
      >
        {starting ? "Starting…" : label}
      </button>
      {error && (
        <span className="repository-action-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
