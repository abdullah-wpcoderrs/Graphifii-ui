"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchProjects } from "../lib/api";
import { mapProject, statusLabel, statusTone, type DashboardProject } from "../lib/dashboard";
import { ApiError } from "../lib/api-errors";
import { EmptyState } from "./empty-state";
import { ErrorState, Spinner } from "./ui";

type ScreenView = "loading" | "empty" | "error" | "list";

function ProjectAction({ project }: { project: DashboardProject }) {
  if (project.status === "READY") {
    return (
      <Link className="repository-action" href={`/workspace/${project.id}`}>
        Resume Workspace
      </Link>
    );
  }

  if (project.status === "FAILED") {
    return (
      <Link className="repository-action is-retry" href={`/projects/${project.id}/launch`}>
        Retry
      </Link>
    );
  }

  return (
    <Link className="repository-action" href={`/projects/${project.id}/launch`}>
      View Progress
    </Link>
  );
}

function ProjectRow({ project }: { project: DashboardProject }) {
  return (
    <article className="repository-row">
      <div className="repository-identity">
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

      <div className="repository-state">
        <span className={`repository-state-badge is-${statusTone(project.status)}`}>
          <i aria-hidden="true" />
          {statusLabel(project.status)}
        </span>
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
    <div className="page-content">
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
