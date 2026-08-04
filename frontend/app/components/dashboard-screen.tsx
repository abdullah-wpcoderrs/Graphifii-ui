"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchProjects } from "../lib/api";
import { mapProject, statusLabel, statusTone, type DashboardProject } from "../lib/dashboard";
import { ApiError } from "../lib/api-errors";
import { EmptyState } from "./empty-state";
import { RerunProjectButton } from "./rerun-project-button";
import { ErrorState, Spinner } from "./ui";

type ScreenView = "loading" | "empty" | "error" | "list";

function ResumeIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <path d="M7 4h9v9" />
      <path d="M16 4 8.5 11.5" />
      <path d="M12 8v7a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1h4" />
    </svg>
  );
}

function RerunIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <path d="M15.5 6.5A6 6 0 0 0 4.6 8" />
      <path d="M4.5 13.5A6 6 0 0 0 15.4 12" />
      <path d="M4 4.5v3.5h3.5" />
      <path d="M16 15.5V12h-3.5" />
    </svg>
  );
}

function ViewProgressIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <circle cx="10" cy="10" r="6.5" />
      <path d="M10 6.5V10l2.5 1.5" />
    </svg>
  );
}

function WorkspaceMissingIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <path d="M10 3.5 17 15.5H3z" />
      <path d="M10 8v3.5" />
      <circle cx="10" cy="13.6" r="0.4" fill="currentColor" stroke="none" />
    </svg>
  );
}

type IconActionProps = {
  tooltip: string;
  className?: string;
  href?: string;
  onClick?: () => void;
  disabled?: boolean;
  children: React.ReactNode;
};

function IconAction({ tooltip, className = "", href, onClick, disabled, children }: IconActionProps) {
  const classes = `icon-action ${className}`.trim();

  if (href) {
    return (
      <Link className={classes} href={href} aria-label={tooltip} data-tooltip={tooltip}>
        {children}
      </Link>
    );
  }

  return (
    <button
      type="button"
      className={classes}
      aria-label={tooltip}
      data-tooltip={tooltip}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

function ProjectAction({ project }: { project: DashboardProject }) {
  if (project.status === "READY" && project.workspaceMissing) {
    return (
      <RerunProjectButton
        className="icon-action is-rerun"
        label=""
        renderIcon
        tooltip="Workspace files were lost — rerun extraction"
        project={{
          repoFullName: project.repoFullName,
          repoUrl: project.repoUrl,
          provider: project.provider,
          defaultBranch: project.defaultBranch,
        }}
      />
    );
  }

  if (project.status === "READY") {
    return (
      <div className="repository-action-cluster repository-action-cluster-icons">
        <IconAction tooltip="Resume workspace" href={`/workspace/${project.id}`}>
          <ResumeIcon />
        </IconAction>
        <RerunProjectButton
          className="icon-action is-rerun"
          label=""
          renderIcon
          tooltip="Rerun extraction"
          project={{
            repoFullName: project.repoFullName,
            repoUrl: project.repoUrl,
            provider: project.provider,
            defaultBranch: project.defaultBranch,
          }}
        />
      </div>
    );
  }

  if (project.status === "FAILED") {
    return (
      <IconAction tooltip="Retry" className="is-retry" href={`/projects/${project.id}/launch`}>
        <RerunIcon />
      </IconAction>
    );
  }

  return (
    <IconAction tooltip="View progress" href={`/projects/${project.id}/launch`}>
      <ViewProgressIcon />
    </IconAction>
  );
}

function ProjectRow({ project }: { project: DashboardProject }) {
  const showWorkspaceMissing = project.status === "READY" && project.workspaceMissing;

  return (
    <article className="repository-row">
      <div className="repository-identity repository-identity-single-line">
        <div className="repository-mark" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div>
          <h2>
            <span>{project.owner}/</span>
            {project.name}
          </h2>
        </div>
      </div>

      <dl className="repository-timing">
        <div>
          <dt>Last updated</dt>
          <dd>{project.updatedLabel}</dd>
        </div>
      </dl>

      <div className="repository-state repository-state-inline">
        {showWorkspaceMissing ? (
          <span
            className="repository-state-badge is-failed"
            data-tooltip="The workspace data for this project was lost and needs to be re-extracted"
          >
            <WorkspaceMissingIcon />
            Workspace lost
          </span>
        ) : (
          <span className={`repository-state-badge is-${statusTone(project.status)}`}>
            <i aria-hidden="true" />
            {statusLabel(project.status)}
          </span>
        )}
        <ProjectAction project={project} />
      </div>
    </article>
  );
}

export function DashboardScreen() {
  const [projects, setProjects] = useState<DashboardProject[] | null>(null);
  const [view, setView] = useState<ScreenView>("loading");

  function load() {
    setView("loading");
    fetchProjects()
      .then((result) => {
        const mapped = result.map(mapProject);
        setProjects(mapped);
        setView(mapped.length === 0 ? "empty" : "list");
      })
      .catch((error) => {
        setProjects([]);
        setView("error");
        if (error instanceof ApiError && error.isUnauthorized) {
          // The (authenticated) layout's SessionProvider handles the
          // redirect for expired sessions — nothing further to do here.
        }
      });
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial data load on mount, not a synchronous render-time update
    load();
  }, []);

  if (view === "loading") {
    return (
      <div className="page-content page-content-centered">
        <Spinner size="lg" label="Loading recent projects" />
      </div>
    );
  }

  if (view === "error") {
    return (
      <div className="page-content">
        <ErrorState
          title="Could not load your projects"
          description="Retry the request; your workspaces are unchanged."
          onRetry={load}
        />
      </div>
    );
  }

  if (view === "empty" || !projects) {
    return (
      <div className="page-content">
        <header className="page-header">
          <h1>Dashboard</h1>
          <p>Recently graphed projects appear here once you launch one.</p>
        </header>
        <EmptyState
          title="No projects yet"
          description="Visit Repositories to launch your first Graphify workspace."
          action={{ label: "Go to Repositories", href: "/repositories" }}
        />
      </div>
    );
  }

  return (
    <div className="page-content page-content-wide">
      <header className="page-header">
        <h1>Dashboard</h1>
        <p>Your most recently graphed projects, newest first.</p>
      </header>

      <section className="repository-list" aria-label="Recent projects">
        <header className="repository-list-header">
          <span>Project</span>
          <span>Activity</span>
          <span>Graphify state</span>
        </header>
        {projects.map((project) => (
          <ProjectRow key={project.id} project={project} />
        ))}
      </section>
    </div>
  );
}
