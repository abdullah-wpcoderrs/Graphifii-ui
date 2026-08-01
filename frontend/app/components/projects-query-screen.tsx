"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { fetchProject, fetchProjectGraph, fetchProjects, type Project } from "../lib/api";
import { mapProject, statusLabel, statusTone, type DashboardProject } from "../lib/dashboard";
import { buildGraphView, type RawGraph } from "../lib/graph";
import { ErrorState, Spinner } from "./ui";
import { EmptyState } from "./empty-state";

type AgentMessage = {
  id: string;
  role: "assistant" | "user";
  content: string;
};

type GraphSummary = {
  nodeCount: number;
  edgeCount: number;
  communityCount: number;
};

type DetailState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "not-ready"; project: Project }
  | { status: "ready"; project: Project; summary: GraphSummary };

const SUGGESTED_PROMPTS = [
  "What are the largest communities in this graph?",
  "Which files have the most relationships?",
  "Summarize the overall architecture",
];

export function ProjectsQueryScreen() {
  const [projects, setProjects] = useState<DashboardProject[] | null>(null);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DetailState>({ status: "idle" });
  const [threads, setThreads] = useState<Record<string, AgentMessage[]>>({});
  const [prompt, setPrompt] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const responseTimer = useRef<number | null>(null);

  function loadProjects() {
    setProjectsError(null);
    fetchProjects()
      .then((result) => {
        const mapped = result.map(mapProject);
        setProjects(mapped);
        if (mapped.length > 0) {
          setSelectedId((current) => current ?? mapped[0].id);
        }
      })
      .catch((error) => {
        setProjects([]);
        setProjectsError(error instanceof Error ? error.message : "Could not load projects");
      });
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial data load on mount, not a synchronous render-time update
    loadProjects();
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- data load triggered by selection change, not a synchronous render-time update
    setDetail({ status: "loading" });

    fetchProject(selectedId)
      .then(async (project) => {
        if (cancelled) return;
        if (project.status !== "READY") {
          setDetail({ status: "not-ready", project });
          return;
        }
        const rawGraph = await fetchProjectGraph(selectedId);
        if (cancelled) return;
        const view = buildGraphView((rawGraph ?? {}) as RawGraph);
        setDetail({
          status: "ready",
          project,
          summary: {
            nodeCount: view.nodeCount,
            edgeCount: view.edgeCount,
            communityCount: view.communityCount,
          },
        });
      })
      .catch((error) => {
        if (cancelled) return;
        setDetail({
          status: "error",
          message: error instanceof Error ? error.message : "Could not load this project",
        });
      });

    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  useEffect(
    () => () => {
      if (responseTimer.current) window.clearTimeout(responseTimer.current);
    },
    [],
  );

  const messages = useMemo(
    () => (selectedId ? (threads[selectedId] ?? []) : []),
    [selectedId, threads],
  );

  function appendMessage(id: string, message: AgentMessage) {
    setThreads((current) => ({
      ...current,
      [id]: [...(current[id] ?? []), message],
    }));
  }

  function submitPrompt(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = prompt.trim();
    if (!value || isStreaming || !selectedId || detail.status !== "ready") return;

    const targetId = selectedId;
    appendMessage(targetId, { id: `user-${Date.now()}`, role: "user", content: value });
    setPrompt("");
    setIsStreaming(true);

    const summary = detail.summary;
    responseTimer.current = window.setTimeout(() => {
      appendMessage(targetId, {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: `Graph-aware querying isn't wired up yet, so I can't answer that directly. This project's graph currently has ${summary.nodeCount} nodes, ${summary.edgeCount} relationships, and ${summary.communityCount} communities.`,
      });
      setIsStreaming(false);
      responseTimer.current = null;
    }, 900);
  }

  if (projects === null) {
    return (
      <div className="page-content page-content-centered">
        <Spinner size="lg" label="Loading projects" />
      </div>
    );
  }

  if (projectsError) {
    return (
      <div className="page-content">
        <ErrorState title="Could not load projects" description={projectsError} onRetry={loadProjects} />
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="page-content">
        <header className="page-header">
          <h1>Projects</h1>
          <p>Ask questions about a graphed codebase once you have launched one.</p>
        </header>
        <EmptyState
          title="No projects yet"
          description="Visit Repositories to launch your first Graphify workspace."
          action={{ label: "Go to Repositories", href: "/repositories" }}
        />
      </div>
    );
  }

  const selected = projects.find((project) => project.id === selectedId) ?? null;

  return (
    <div className="projects-query-page">
      <aside className="projects-query-list" aria-label="Your projects">
        <header>
          <span>Projects</span>
          <strong>{projects.length}</strong>
        </header>
        <div className="projects-query-list-items">
          {projects.map((project) => (
            <button
              key={project.id}
              type="button"
              className={`projects-query-item ${selectedId === project.id ? "is-active" : ""}`}
              onClick={() => setSelectedId(project.id)}
            >
              <span className={`projects-query-item-dot is-${statusTone(project.status)}`} aria-hidden="true" />
              <span className="projects-query-item-text">
                <strong>{project.name}</strong>
                <em>{project.owner}</em>
              </span>
            </button>
          ))}
        </div>
      </aside>

      <section className="projects-query-main" aria-label="Ask the graph">
        {!selected ? (
          <div className="workspace-empty-note">Select a project to get started.</div>
        ) : (
          <>
            <header className="projects-query-header">
              <div>
                <span className={`repository-state-badge is-${statusTone(selected.status)}`}>
                  <i aria-hidden="true" />
                  {statusLabel(selected.status)}
                </span>
                <h1>
                  {selected.owner}/{selected.name}
                </h1>
              </div>
              {detail.status === "ready" && (
                <dl className="projects-query-stats">
                  <div>
                    <dt>Nodes</dt>
                    <dd>{detail.summary.nodeCount}</dd>
                  </div>
                  <div>
                    <dt>Relationships</dt>
                    <dd>{detail.summary.edgeCount}</dd>
                  </div>
                  <div>
                    <dt>Communities</dt>
                    <dd>{detail.summary.communityCount}</dd>
                  </div>
                </dl>
              )}
            </header>

            {detail.status === "loading" && (
              <div className="projects-query-state">
                <Spinner size="md" label="Loading graph" />
              </div>
            )}

            {detail.status === "error" && (
              <div className="projects-query-state">
                <ErrorState title="Could not load this project" description={detail.message} />
              </div>
            )}

            {detail.status === "not-ready" && (
              <div className="projects-query-state">
                <p>
                  This project hasn&apos;t finished graphing yet.{" "}
                  <Link href={`/projects/${selected.id}/launch`}>View progress</Link>.
                </p>
              </div>
            )}

            {detail.status === "ready" && (
              <>
                <div className="agent-conversation projects-query-conversation">
                  {messages.length === 0 && (
                    <p className="workspace-empty-note">
                      Ask a question about this codebase&apos;s graph below.
                    </p>
                  )}
                  {messages.map((message) => (
                    <article className={`agent-message is-${message.role}`} key={message.id}>
                      <span>{message.role === "assistant" ? "Graphify" : "You"}</span>
                      <p>{message.content}</p>
                    </article>
                  ))}
                  {isStreaming && (
                    <article className="agent-message is-assistant is-streaming" role="status">
                      <span>Graphify</span>
                      <p>
                        Tracing graph relationships
                        <i />
                        <i />
                        <i />
                      </p>
                    </article>
                  )}
                </div>

                <div className="agent-suggestions" aria-label="Suggested queries">
                  {SUGGESTED_PROMPTS.map((suggestion) => (
                    <button type="button" key={suggestion} onClick={() => setPrompt(suggestion)}>
                      {suggestion}
                    </button>
                  ))}
                </div>

                <form className="agent-composer projects-query-composer" onSubmit={submitPrompt}>
                  <label>
                    <span className="sr-only">Ask a question about this project</span>
                    <textarea
                      value={prompt}
                      onChange={(event) => setPrompt(event.target.value)}
                      placeholder="Describe a task or ask a question…"
                      rows={2}
                    />
                  </label>
                  <div>
                    <span>Graph-aware context enabled</span>
                    <button aria-label="Send prompt" disabled={!prompt.trim() || isStreaming} type="submit">
                      Send
                    </button>
                  </div>
                </form>
              </>
            )}
          </>
        )}
      </section>
    </div>
  );
}
