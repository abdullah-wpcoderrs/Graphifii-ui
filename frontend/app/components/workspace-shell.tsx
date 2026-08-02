"use client";

import type { OnMount } from "@monaco-editor/react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  type FormEvent,
  type PointerEvent as ReactPointerEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { FaPython } from "react-icons/fa6";
import {
  VscChevronRight,
  VscFile,
  VscFolderOpened,
  VscMarkdown,
} from "react-icons/vsc";
import {
  createPullRequest,
  dismissAgentChange,
  fetchProject,
  fetchProjectFileContent,
  fetchProjectFiles,
  fetchProjectGraph,
  saveAgentChange,
  type AgentChange,
  type AgentMessage,
  type Project,
} from "../lib/api";
import { ApiError } from "../lib/api-errors";
import { getPublicWsUrl } from "../lib/env";
import {
  buildFileGroups,
  buildGraphView,
  type RawFileTree,
  type RawGraph,
  type WorkspaceFileEntry,
  type WorkspaceFileGroup,
  type WorkspaceGraphEdge,
  type WorkspaceGraphNode,
} from "../lib/graph";
import { AgentDiffDialog } from "./agent-diff-dialog";
import { RerunProjectButton } from "./rerun-project-button";
import { ErrorState, Spinner } from "./ui";

const MAX_WS_BACKOFF_MS = 15000;

const MonacoEditor = dynamic(
  () => import("@monaco-editor/react").then((module) => module.Editor),
  {
    ssr: false,
    loading: () => (
      <div className="workspace-module-loading" role="status">
        Loading editor…
      </div>
    ),
  },
);

const ArchitectureGraph = dynamic(() => import("./architecture-graph"), {
  ssr: false,
  loading: () => (
    <div className="workspace-module-loading" role="status">
      Loading architecture graph…
    </div>
  ),
});

type WorkspacePanel = "editor" | "graph" | "agent";
type RightPanelTab = "agent" | "output";

type WorkspaceShellProps = {
  projectId: string;
};

type StreamingFile = {
  before: string | null;
  after: string;
  isNewFile: boolean;
  done: boolean;
};

type AgentConnectionState = "connecting" | "open" | "closed";

type OutputLogEntry = {
  time: string;
  tone: "info" | "success";
  message: string;
};

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "redirecting" }
  | {
      status: "ready";
      project: Project;
      fileGroups: WorkspaceFileGroup[];
      totalFiles: number;
      filesTruncated: boolean;
      graphNodes: WorkspaceGraphNode[];
      graphEdges: WorkspaceGraphEdge[];
      graphCommunityCount: number;
    };

function nowLabel() {
  return new Date().toLocaleTimeString([], { hour12: false });
}

function FileTypeIcon({ language }: { language: string }) {
  if (language === "python") {
    return <FaPython aria-hidden="true" className="file-type-icon is-python" />;
  }

  if (language === "markdown") {
    return (
      <VscMarkdown aria-hidden="true" className="file-type-icon is-markdown" />
    );
  }

  return <VscFile aria-hidden="true" className="file-type-icon is-generic" />;
}

function Icon({
  name,
}: {
  name: "branch" | "chevron" | "file" | "send" | "stop" | "spark";
}) {
  const paths = {
    branch: (
      <>
        <circle cx="5" cy="4" r="2" />
        <circle cx="5" cy="16" r="2" />
        <circle cx="15" cy="7" r="2" />
        <path d="M5 6v8M7 14c5 0 8-2 8-5" />
      </>
    ),
    chevron: <path d="m7 9 3 3 3-3" />,
    file: (
      <>
        <path d="M6 2.5h5l3 3V17.5H6z" />
        <path d="M11 2.5v3h3" />
      </>
    ),
    send: <path d="m3 10 14-7-4.5 14-2.5-5-7-2Zm7 2 3-3" />,
    stop: <rect x="5" y="5" width="10" height="10" rx="1" />,
    spark: (
      <>
        <path d="m10 2 1.4 4.6L16 8l-4.6 1.4L10 14l-1.4-4.6L4 8l4.6-1.4L10 2Z" />
        <path d="m16 13 .7 2.3L19 16l-2.3.7L16 19l-.7-2.3L13 16l2.3-.7L16 13Z" />
      </>
    ),
  };

  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      {paths[name]}
    </svg>
  );
}

export function WorkspaceShell({ projectId }: WorkspaceShellProps) {
  const router = useRouter();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [activeFilePath, setActiveFilePath] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<WorkspaceGraphNode | null>(null);
  const [activePanel, setActivePanel] = useState<WorkspacePanel>("editor");
  const [rightTab, setRightTab] = useState<RightPanelTab>("agent");
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [changes, setChanges] = useState<AgentChange[]>([]);
  const [streamingProse, setStreamingProse] = useState("");
  const [streamingFiles, setStreamingFiles] = useState<Record<string, StreamingFile>>({});
  const [agentConnection, setAgentConnection] = useState<AgentConnectionState>("connecting");
  const [agentError, setAgentError] = useState<string | null>(null);
  const [showDiffDialog, setShowDiffDialog] = useState(false);
  const [outputLog, setOutputLog] = useState<OutputLogEntry[]>([]);
  const [prompt, setPrompt] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [logFilter, setLogFilter] = useState("all");
  const [leftWidth, setLeftWidth] = useState(35);
  const [rightWidth, setRightWidth] = useState(25);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileContentError, setFileContentError] = useState<string | null>(null);
  const [fileContentLoading, setFileContentLoading] = useState(false);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const agentSocketRef = useRef<WebSocket | null>(null);
  const agentRetryTimerRef = useRef<number | null>(null);
  const agentBackoffRef = useRef(1000);

  function load() {
    setState({ status: "loading" });

    fetchProject(projectId)
      .then(async (project) => {
        if (project.status !== "READY") {
          setState({ status: "redirecting" });
          router.replace(`/projects/${projectId}/launch`);
          return;
        }

        const [rawGraph, rawFiles] = await Promise.all([
          fetchProjectGraph(projectId),
          fetchProjectFiles(projectId).catch(() => null),
        ]);

        const graphView = buildGraphView((rawGraph ?? {}) as RawGraph);
        const fileSummary = rawFiles
          ? buildFileGroups(rawFiles as RawFileTree)
          : { groups: [], totalFiles: 0, renderedFiles: 0, truncated: false };

        setState({
          status: "ready",
          project,
          fileGroups: fileSummary.groups,
          totalFiles: fileSummary.totalFiles,
          filesTruncated: fileSummary.truncated,
          graphNodes: graphView.nodes,
          graphEdges: graphView.edges,
          graphCommunityCount: graphView.communityCount,
        });

        const log: OutputLogEntry[] = [
          { time: nowLabel(), tone: "info", message: "Workspace opened." },
          {
            time: nowLabel(),
            tone: "success",
            message: `graph.json loaded · ${graphView.nodeCount} nodes, ${graphView.edgeCount} links.`,
          },
        ];
        if (rawFiles) {
          log.push({
            time: nowLabel(),
            tone: "success",
            message: `files.json loaded · ${fileSummary.totalFiles} files${
              fileSummary.truncated ? " (truncated)" : ""
            }.`,
          });
        }
        setOutputLog(log);

        const firstFile = fileSummary.groups[0]?.files[0]?.path ?? null;
        setActiveFilePath(firstFile);
      })
      .catch((error) => {
        setState({
          status: "error",
          message:
            error instanceof ApiError
              ? error.message
              : "Could not load this workspace.",
        });
      });
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial data load on mount, not a synchronous render-time update
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load() is stable for a given projectId; re-running on its identity would loop
  }, [projectId]);

  const allFiles: WorkspaceFileEntry[] =
    state.status === "ready" ? state.fileGroups.flatMap((group) => group.files) : [];
  const activeFile =
    allFiles.find((file) => file.path === activeFilePath) ?? allFiles[0] ?? null;

  const centerWidth = Math.max(30, 100 - leftWidth - rightWidth);

  useEffect(() => {
    const saved = window.localStorage.getItem(`graphify-pane-widths:${projectId}`);
    if (!saved) return;

    try {
      const value = JSON.parse(saved) as { left?: number; right?: number };
      const frame = window.requestAnimationFrame(() => {
        if (typeof value.left === "number") setLeftWidth(value.left);
        if (typeof value.right === "number") setRightWidth(value.right);
      });
      return () => window.cancelAnimationFrame(frame);
    } catch {
      window.localStorage.removeItem(`graphify-pane-widths:${projectId}`);
    }
  }, [projectId]);

  useEffect(() => {
    window.localStorage.setItem(
      `graphify-pane-widths:${projectId}`,
      JSON.stringify({ left: leftWidth, right: rightWidth }),
    );
  }, [leftWidth, projectId, rightWidth]);

  // Real conversation over a real socket: replays history on connect (a
  // refresh must show the real conversation, not an empty panel), and
  // reconnects with backoff on an unexpected drop, mirroring the launch
  // screen's provisioning WebSocket client.
  useEffect(() => {
    if (state.status !== "ready") return;

    const wsBase = getPublicWsUrl();
    if (!wsBase) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- config validation on mount, not a synchronous render-time update
      setAgentError("The backend API URL is not configured.");
      return;
    }

    let cancelled = false;

    function connect() {
      if (cancelled) return;
      setAgentConnection("connecting");
      const socket = new WebSocket(`${wsBase}/ws/projects/${projectId}/agent`);
      agentSocketRef.current = socket;

      socket.onopen = () => {
        if (cancelled) return;
        setAgentConnection("open");
        agentBackoffRef.current = 1000;
      };

      socket.onmessage = (event) => {
        if (cancelled) return;
        let payload: Record<string, unknown>;
        try {
          payload = JSON.parse(event.data);
        } catch {
          return;
        }

        switch (payload.type) {
          case "history": {
            setMessages((payload.messages as AgentMessage[]) ?? []);
            setChanges((payload.changes as AgentChange[]) ?? []);
            break;
          }
          case "user_message": {
            setMessages((current) => [...current, payload.message as AgentMessage]);
            break;
          }
          case "message_start": {
            setIsStreaming(true);
            setStreamingProse("");
            setStreamingFiles({});
            setAgentError(null);
            break;
          }
          case "text_token": {
            setStreamingProse((current) => current + (payload.text as string));
            break;
          }
          case "file_start": {
            const path = payload.path as string;
            setStreamingFiles((current) => ({
              ...current,
              [path]: {
                before: (payload.before_content as string | null) ?? null,
                after: "",
                isNewFile: Boolean(payload.is_new_file),
                done: false,
              },
            }));
            break;
          }
          case "file_token": {
            const path = payload.path as string;
            setStreamingFiles((current) => {
              const existing = current[path];
              if (!existing) return current;
              return { ...current, [path]: { ...existing, after: existing.after + (payload.text as string) } };
            });
            break;
          }
          case "file_end": {
            const path = payload.path as string;
            setStreamingFiles((current) => {
              const existing = current[path];
              if (!existing) return current;
              return { ...current, [path]: { ...existing, done: true } };
            });
            break;
          }
          case "message_end": {
            setIsStreaming(false);
            setMessages((current) => [...current, payload.message as AgentMessage]);
            const newChanges = (payload.changes as AgentChange[]) ?? [];
            if (newChanges.length > 0) {
              setChanges((current) => {
                const supersededPaths = new Set(newChanges.map((c) => c.path));
                const kept = current.filter(
                  (c) => !(supersededPaths.has(c.path) && c.status === "PROPOSED"),
                );
                return [...kept, ...newChanges];
              });
            }
            setStreamingProse("");
            setStreamingFiles({});
            break;
          }
          case "error": {
            setIsStreaming(false);
            setAgentError(payload.message as string);
            break;
          }
          default:
            break;
        }
      };

      socket.onclose = (closeEvent) => {
        if (cancelled) return;
        setAgentConnection("closed");
        setIsStreaming(false);

        if (closeEvent.code === 4401) {
          setAgentError("Your session has expired. Sign in again to continue.");
          return;
        }
        if (closeEvent.code === 4403) {
          setAgentError("Your account has been suspended.");
          return;
        }
        if (closeEvent.code === 4404) {
          setAgentError("This project no longer exists.");
          return;
        }
        if (closeEvent.code === 1000) return;

        const delay = Math.min(agentBackoffRef.current, MAX_WS_BACKOFF_MS);
        agentBackoffRef.current = Math.min(agentBackoffRef.current * 2, MAX_WS_BACKOFF_MS);
        agentRetryTimerRef.current = window.setTimeout(connect, delay);
      };

      socket.onerror = () => {
        socket.close();
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (agentRetryTimerRef.current) window.clearTimeout(agentRetryTimerRef.current);
      agentSocketRef.current?.close(1000);
      agentSocketRef.current = null;
    };
  }, [projectId, state.status]);

  // Fetch real file content for the active file — read live from the git
  // provider (see GET /api/projects/:id/files/{path}), not a stored snapshot.
  useEffect(() => {
    if (!activeFile) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- clearing stale content when the selection itself changes, not a render-time update
      setFileContent(null);
      setFileContentError(null);
      return;
    }

    let cancelled = false;
    setFileContentLoading(true);
    setFileContentError(null);

    fetchProjectFileContent(projectId, activeFile.path)
      .then((result) => {
        if (cancelled) return;
        setFileContent(result.content);
      })
      .catch((error) => {
        if (cancelled) return;
        setFileContent(null);
        setFileContentError(
          error instanceof ApiError ? error.message : "Could not load this file's contents.",
        );
      })
      .finally(() => {
        if (!cancelled) setFileContentLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, activeFile]);

  const editorOptions = useMemo(
    () => ({
      automaticLayout: true,
      fontFamily: "'Geist Mono', 'JetBrains Mono', monospace",
      fontSize: 15,
      lineHeight: 23,
      minimap: { enabled: false },
      padding: { top: 14 },
      readOnly: true,
      renderLineHighlight: "all" as const,
      scrollBeyondLastLine: false,
      smoothScrolling: true,
      wordWrap: "on" as const,
    }),
    [],
  );

  function openFile(path: string) {
    setActiveFilePath(path);
    setActivePanel("editor");
    setSelectedNode((current) => (current?.filePath === path ? current : null));
  }

  function handleGraphNode(node: WorkspaceGraphNode) {
    setSelectedNode(node);
    if (node.filePath && allFiles.some((file) => file.path === node.filePath)) {
      setActiveFilePath(node.filePath);
    }
  }

  function startResize(
    side: "left" | "right",
    event: ReactPointerEvent<HTMLDivElement>,
  ) {
    event.currentTarget.setPointerCapture(event.pointerId);

    const handleMove = (pointerEvent: PointerEvent) => {
      const container = workspaceRef.current?.getBoundingClientRect();
      if (!container) return;
      const pointerPercent =
        ((pointerEvent.clientX - container.left) / container.width) * 100;

      if (side === "left") {
        setLeftWidth(
          Math.min(50, Math.max(25, Math.min(pointerPercent, 70 - rightWidth))),
        );
      } else {
        const proposedRight = 100 - pointerPercent;
        setRightWidth(
          Math.min(40, Math.max(20, Math.min(proposedRight, 70 - leftWidth))),
        );
      }
    };

    const handleUp = () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
  }

  function submitPrompt(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = prompt.trim();
    const socket = agentSocketRef.current;
    if (!value || isStreaming || agentConnection !== "open" || !socket) return;

    setAgentError(null);
    socket.send(JSON.stringify({ type: "user_message", content: value }));
    setPrompt("");
  }

  function stopStreaming() {
    // There is no server-side "abort this generation" call in this phase —
    // the model call already has tokens in flight, and the backend still
    // persists and bills whatever it produces. This only stops the client
    // from rendering further tokens for the in-flight turn by reconnecting;
    // the completed answer will still appear on the next `message_end` or
    // on the next history replay.
    agentSocketRef.current?.close(1000);
    setIsStreaming(false);
    setStreamingProse("");
    setStreamingFiles({});
  }

  async function handleSaveChangeEdit(changeId: string, afterContent: string) {
    const updated = await saveAgentChange(projectId, changeId, afterContent);
    setChanges((current) => current.map((change) => (change.id === updated.id ? updated : change)));
  }

  async function handleDismissChange(changeId: string) {
    await dismissAgentChange(projectId, changeId);
    setChanges((current) => current.filter((change) => change.id !== changeId));
  }

  async function handleDispatchPullRequest(input: {
    title: string;
    body: string;
    changeIds: string[];
  }) {
    const result = await createPullRequest(projectId, { ...input, confirm: true });
    setChanges((current) => current.filter((change) => !input.changeIds.includes(change.id)));
    setShowDiffDialog(false);
    setOutputLog((current) => [
      ...current,
      {
        time: nowLabel(),
        tone: "success",
        message: `Opened ${result.kind} #${result.number} on branch ${result.branch}: ${result.url}`,
      },
    ]);
  }

  if (state.status === "loading" || state.status === "redirecting") {
    return (
      <main className="workspace-page workspace-page-centered">
        <Spinner size="lg" label="Loading workspace" />
      </main>
    );
  }

  if (state.status === "error") {
    return (
      <main className="workspace-page workspace-page-centered">
        <ErrorState title="Could not load this workspace" description={state.message} onRetry={load} />
      </main>
    );
  }

  const filteredLogs =
    logFilter === "all" ? outputLog : outputLog.filter((log) => log.tone === logFilter);

  return (
    <main className="workspace-page">
      <header className="workspace-header">
        <div className="workspace-repository">
          <Link href="/dashboard" aria-label="Return to dashboard">
            <span aria-hidden="true">G</span>
          </Link>
          <strong>{state.project.repo_name}</strong>
        </div>

        <div className="workspace-connection" role="status">
          <i aria-hidden="true" />
          Graph ready · {state.graphNodes.length} nodes
        </div>

        <div className="workspace-header-actions">
          <span>{state.totalFiles} files</span>
          {state.filesTruncated && <span title="Only part of the tree loaded">Truncated</span>}
          <RerunProjectButton
            className="workspace-rerun-button"
            label="Rerun"
            project={{
              repoFullName: state.project.repo_name,
              repoUrl: state.project.repo_url,
              provider: state.project.provider,
              defaultBranch: state.project.default_branch,
            }}
          />
        </div>
      </header>

      <nav className="workspace-mobile-tabs" aria-label="Workspace panels">
        {(["editor", "graph", "agent"] as WorkspacePanel[]).map((panel) => (
          <button
            className={activePanel === panel ? "is-active" : ""}
            key={panel}
            type="button"
            onClick={() => setActivePanel(panel)}
          >
            {panel}
          </button>
        ))}
      </nav>

      <div
        className="workspace-grid"
        ref={workspaceRef}
        style={{
          gridTemplateColumns: `calc(${leftWidth}% - 2px) 5px calc(${centerWidth}% - 6px) 5px calc(${rightWidth}% - 2px)`,
        }}
      >
        <section
          className={`workspace-pane editor-pane ${
            activePanel === "editor" ? "is-mobile-active" : ""
          }`}
          aria-label="Code editor"
        >
          <aside className="file-explorer">
            <header>
              <span>Explorer</span>
              <strong>{state.totalFiles}</strong>
            </header>
            <div className="file-tree">
              {state.fileGroups.length === 0 ? (
                <p className="workspace-empty-note">No files were reported for this repository.</p>
              ) : (
                state.fileGroups.map((group) => (
                  <details open key={group.label}>
                    <summary>
                      <VscChevronRight
                        aria-hidden="true"
                        className="tree-chevron"
                      />
                      <VscFolderOpened
                        aria-hidden="true"
                        className="folder-type-icon"
                      />
                      <span>{group.label}</span>
                    </summary>
                    {group.files.map((file) => (
                      <button
                        className={activeFilePath === file.path ? "is-active" : ""}
                        key={file.path}
                        type="button"
                        onClick={() => openFile(file.path)}
                      >
                        <FileTypeIcon language={file.language} />
                        <span>{file.name}</span>
                      </button>
                    ))}
                  </details>
                ))
              )}
            </div>
          </aside>

          <div className="editor-workbench">
            <div className="editor-tabs">
              {activeFile ? (
                <button className="is-active" type="button">
                  <FileTypeIcon language={activeFile.language} />
                  {activeFile.name}
                </button>
              ) : (
                <span className="editor-tabs-empty">No file selected</span>
              )}
            </div>

            <div className="editor-surface">
              {activeFile && fileContentLoading ? (
                <div className="workspace-module-loading" role="status">
                  Loading {activeFile.name}…
                </div>
              ) : activeFile && fileContentError ? (
                <div className="workspace-empty-note">{fileContentError}</div>
              ) : activeFile ? (
                <MonacoEditor
                  language={activeFile.language}
                  onMount={(editor) => {
                    editorRef.current = editor;
                  }}
                  options={editorOptions}
                  path={activeFile.path}
                  theme="vs-dark"
                  value={fileContent ?? ""}
                />
              ) : (
                <div className="workspace-empty-note">
                  Select a file from the explorer to see its details.
                </div>
              )}
            </div>
            <footer className="editor-statusbar">
              <span>{activeFile?.language ?? "—"}</span>
              {activeFile && <span>{activeFile.size.toLocaleString()} bytes</span>}
              {selectedNode && selectedNode.filePath === activeFile?.path && (
                <span>
                  Ln {selectedNode.line} · {selectedNode.label}
                </span>
              )}
            </footer>
          </div>
        </section>

        <div
          className="workspace-resize-handle"
          role="separator"
          aria-label="Resize editor panel"
          aria-orientation="vertical"
          onPointerDown={(event) => startResize("left", event)}
        />

        <section
          className={`workspace-pane graph-pane ${
            activePanel === "graph" ? "is-mobile-active" : ""
          }`}
          aria-label="Architecture graph"
        >
          <header className="workspace-pane-header">
            <div>
              <span>Architecture</span>
              <strong>
                {state.graphCommunityCount} communities · {state.graphNodes.length} nodes
              </strong>
            </div>
            <span>graph.json</span>
          </header>
          <ArchitectureGraph
            nodes={state.graphNodes}
            edges={state.graphEdges}
            activeFilePath={activeFilePath ?? ""}
            onSelectNode={handleGraphNode}
            selectedNodeId={selectedNode?.id ?? null}
          />
        </section>

        <div
          className="workspace-resize-handle"
          role="separator"
          aria-label="Resize agent panel"
          aria-orientation="vertical"
          onPointerDown={(event) => startResize("right", event)}
        />

        <section
          className={`workspace-pane agent-pane ${
            activePanel === "agent" ? "is-mobile-active" : ""
          }`}
          aria-label="Graph-aware agent"
        >
          <div className="agent-tabs" role="tablist" aria-label="Agent views">
            <button
              aria-selected={rightTab === "agent"}
              className={rightTab === "agent" ? "is-active" : ""}
              role="tab"
              type="button"
              onClick={() => setRightTab("agent")}
            >
              Agent
            </button>
            <button
              aria-selected={rightTab === "output"}
              className={rightTab === "output" ? "is-active" : ""}
              role="tab"
              type="button"
              onClick={() => setRightTab("output")}
            >
              Output Log
            </button>
          </div>

          {rightTab === "agent" ? (
            <>
              <div className="agent-conversation">
                <div className="agent-context">
                  <Icon name="spark" />
                  <div>
                    <strong>Graph context attached</strong>
                    <span>
                      {state.graphNodes.length} nodes · {state.graphEdges.length} edges
                      {agentConnection !== "open" && ` · ${agentConnection}…`}
                    </span>
                  </div>
                </div>

                {messages.map((message) => (
                  <article className={`agent-message is-${message.role}`} key={message.id}>
                    <span>{message.role === "assistant" ? "Graphify" : "You"}</span>
                    {message.error ? <p className="agent-message-error">{message.error}</p> : null}
                    {message.content && <p>{message.content}</p>}
                  </article>
                ))}

                {isStreaming && (
                  <article className="agent-message is-assistant is-streaming" role="status">
                    <span>Graphify</span>
                    <p>
                      {streamingProse || "Tracing graph relationships"}
                      {!streamingProse && (
                        <>
                          <i />
                          <i />
                          <i />
                        </>
                      )}
                    </p>
                    {Object.entries(streamingFiles).map(([path, file]) => (
                      <p className="agent-streaming-file" key={path}>
                        {file.done ? "Proposed change to " : "Writing "}
                        <code>{path}</code>
                        {file.isNewFile && " (new file)"}
                      </p>
                    ))}
                  </article>
                )}

                {agentError && (
                  <p className="agent-message-error" role="alert">
                    {agentError}
                  </p>
                )}
              </div>

              {changes.filter((change) => change.status === "PROPOSED").length > 0 && (
                <div className="agent-change-card">
                  <header>
                    <div>
                      <strong>Proposed changes</strong>
                      <span>
                        {changes.filter((change) => change.status === "PROPOSED").length} file
                        {changes.filter((change) => change.status === "PROPOSED").length === 1
                          ? ""
                          : "s"}
                      </span>
                    </div>
                  </header>
                  <ul>
                    {changes
                      .filter((change) => change.status === "PROPOSED")
                      .map((change) => (
                        <li key={change.id}>
                          <Icon name="file" />
                          <span>{change.path}</span>
                          {change.edited_by_user && <i>edited</i>}
                        </li>
                      ))}
                  </ul>
                  <div>
                    <button type="button" onClick={() => setShowDiffDialog(true)}>
                      Review changes
                    </button>
                    <button type="button" onClick={() => setShowDiffDialog(true)}>
                      Prepare PR
                    </button>
                  </div>
                </div>
              )}

              <div className="agent-suggestions" aria-label="Suggested queries">
                {[
                  "Explain the highest-centrality nodes",
                  "Summarize the largest community",
                  "Which nodes have no incoming edges?",
                ].map((suggestion) => (
                  <button
                    type="button"
                    key={suggestion}
                    onClick={() => setPrompt(suggestion)}
                  >
                    {suggestion}
                  </button>
                ))}
              </div>

              <form className="agent-composer" onSubmit={submitPrompt}>
                <label>
                  <span className="sr-only">Ask the graph-aware agent</span>
                  <textarea
                    value={prompt}
                    onChange={(event) => setPrompt(event.target.value)}
                    placeholder="Ask about the codebase…"
                    rows={3}
                  />
                </label>
                <div>
                  <span>
                    {agentConnection === "open" ? "Graph-aware context enabled" : "Reconnecting…"}
                  </span>
                  {isStreaming ? (
                    <button
                      aria-label="Stop generation"
                      type="button"
                      onClick={stopStreaming}
                    >
                      <Icon name="stop" />
                    </button>
                  ) : (
                    <button
                      aria-label="Send prompt"
                      disabled={!prompt.trim() || agentConnection !== "open"}
                      type="submit"
                    >
                      <Icon name="send" />
                    </button>
                  )}
                </div>
              </form>
            </>
          ) : (
            <div className="output-log">
              <div className="output-log-toolbar">
                <span>Workspace events</span>
                <select
                  aria-label="Filter output logs"
                  value={logFilter}
                  onChange={(event) => setLogFilter(event.target.value)}
                >
                  <option value="all">All events</option>
                  <option value="info">Info</option>
                  <option value="success">Success</option>
                </select>
              </div>
              <div className="output-log-lines" aria-live="polite">
                {filteredLogs.map((log) => (
                  <article key={`${log.time}-${log.message}`}>
                    <time>{log.time}</time>
                    <span className={`is-${log.tone}`}>{log.tone}</span>
                    <p>{log.message}</p>
                  </article>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>

      {showDiffDialog && (
        <AgentDiffDialog
          changes={changes.filter((change) => change.status === "PROPOSED")}
          repoName={state.project.repo_name}
          defaultBranch={state.project.default_branch}
          changeRequestNoun={state.project.provider === "gitlab" ? "merge request" : "pull request"}
          onSaveEdit={handleSaveChangeEdit}
          onDismiss={handleDismissChange}
          onDispatch={handleDispatchPullRequest}
          onClose={() => setShowDiffDialog(false)}
        />
      )}
    </main>
  );
}
