"use client";

import type { OnMount } from "@monaco-editor/react";
import dynamic from "next/dynamic";
import Link from "next/link";
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
  INITIAL_AGENT_MESSAGES,
  OUTPUT_LOGS,
  WORKSPACE_FILES,
  type AgentMessage,
  type WorkspaceGraphNode,
} from "../lib/workspace-fixtures";

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

const MonacoDiffEditor = dynamic(
  () => import("@monaco-editor/react").then((module) => module.DiffEditor),
  {
    ssr: false,
    loading: () => (
      <div className="workspace-module-loading" role="status">
        Preparing diff…
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
type EditorMode = "source" | "diff";
type RightPanelTab = "agent" | "output";

type WorkspaceShellProps = {
  projectId: string;
};

const FILE_GROUPS = [
  {
    label: "graphify",
    files: WORKSPACE_FILES.filter((file) => file.path.startsWith("graphify/")),
  },
  {
    label: "server",
    files: WORKSPACE_FILES.filter((file) => file.path.startsWith("server/")),
  },
  {
    label: "root",
    files: WORKSPACE_FILES.filter((file) => !file.path.includes("/")),
  },
];

const SUGGESTED_PROMPTS = [
  "Explain the highest-centrality nodes",
  "Trace extraction progress to the WebSocket",
  "Find callers of query_graph",
];

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
  name: "branch" | "chevron" | "file" | "send" | "stop" | "spark" | "pr";
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
    pr: (
      <>
        <circle cx="5" cy="4" r="2" />
        <circle cx="5" cy="16" r="2" />
        <circle cx="15" cy="16" r="2" />
        <path d="M5 6v8M9 5h2a4 4 0 0 1 4 4v5M9 2 6 5l3 3" />
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
  const [activeFilePath, setActiveFilePath] = useState(WORKSPACE_FILES[0].path);
  const [selectedNode, setSelectedNode] =
    useState<WorkspaceGraphNode | null>(null);
  const [editorMode, setEditorMode] = useState<EditorMode>("source");
  const [activePanel, setActivePanel] = useState<WorkspacePanel>("editor");
  const [rightTab, setRightTab] = useState<RightPanelTab>("agent");
  const [messages, setMessages] = useState<AgentMessage[]>(
    INITIAL_AGENT_MESSAGES,
  );
  const [prompt, setPrompt] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [logFilter, setLogFilter] = useState("all");
  const [leftWidth, setLeftWidth] = useState(35);
  const [rightWidth, setRightWidth] = useState(25);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const responseTimer = useRef<number | null>(null);

  const activeFile =
    WORKSPACE_FILES.find((file) => file.path === activeFilePath) ??
    WORKSPACE_FILES[0];
  const changedFiles = WORKSPACE_FILES.filter((file) => file.status);
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

  useEffect(() => {
    if (!selectedNode || !editorRef.current) return;
    editorRef.current.revealLineInCenter(selectedNode.line);
    editorRef.current.setPosition({ lineNumber: selectedNode.line, column: 1 });
  }, [activeFilePath, selectedNode]);

  useEffect(
    () => () => {
      if (responseTimer.current) window.clearTimeout(responseTimer.current);
    },
    [],
  );

  const editorOptions = useMemo(
    () => ({
      automaticLayout: true,
      fontFamily: "'Geist Mono', 'JetBrains Mono', monospace",
      fontSize: 13,
      lineHeight: 21,
      minimap: { enabled: false },
      padding: { top: 14 },
      renderLineHighlight: "all" as const,
      scrollBeyondLastLine: false,
      smoothScrolling: true,
      wordWrap: "off" as const,
    }),
    [],
  );

  function openFile(path: string) {
    setActiveFilePath(path);
    setEditorMode("source");
    setActivePanel("editor");
    const matchingNode = selectedNode?.filePath === path ? selectedNode : null;
    setSelectedNode(matchingNode);
  }

  function handleGraphNode(node: WorkspaceGraphNode) {
    setSelectedNode(node);
    setActiveFilePath(node.filePath);
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
    if (!value || isStreaming) return;

    setMessages((current) => [
      ...current,
      { id: `user-${Date.now()}`, role: "user", content: value },
    ]);
    setPrompt("");
    setIsStreaming(true);

    responseTimer.current = window.setTimeout(() => {
      setMessages((current) => [
        ...current,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content:
            "I traced that request through the Query Engine community. query_graph is the highest-impact entry point; I would inspect its bounded traversal diff before preparing a pull request.",
        },
      ]);
      setIsStreaming(false);
      responseTimer.current = null;
    }, 1200);
  }

  function stopStreaming() {
    if (responseTimer.current) window.clearTimeout(responseTimer.current);
    responseTimer.current = null;
    setIsStreaming(false);
  }

  function inspectDiff() {
    setActiveFilePath("graphify/query.py");
    setEditorMode("diff");
    setActivePanel("editor");
  }

  const filteredLogs =
    logFilter === "all"
      ? OUTPUT_LOGS
      : OUTPUT_LOGS.filter((log) => log.tone === logFilter);

  return (
    <main className="workspace-page">
      <header className="workspace-header">
        <div className="workspace-repository">
          <Link href="/dashboard" aria-label="Return to repository dashboard">
            <span aria-hidden="true">G</span>
          </Link>
          <strong>Graphify-Labs/graphify</strong>
          <button type="button" aria-label="Change active branch">
            <Icon name="branch" />
            main
            <Icon name="chevron" />
          </button>
        </div>

        <div className="workspace-connection" role="status">
          <i aria-hidden="true" />
          Graph ready · 9,416 nodes
        </div>

        <div className="workspace-header-actions">
          <span>{changedFiles.length} changed</span>
          <Link href="/admin/credentials">Admin</Link>
          <button
            className="workspace-pr-button"
            type="button"
            onClick={() => {
              setRightTab("agent");
              setActivePanel("agent");
            }}
          >
            <Icon name="pr" />
            Create Pull Request
          </button>
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
              <strong>{changedFiles.length}</strong>
            </header>
            <div className="file-tree">
              {FILE_GROUPS.map((group) => (
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
                      {file.status && <i aria-label={file.status} />}
                    </button>
                  ))}
                </details>
              ))}
            </div>
          </aside>

          <div className="editor-workbench">
            <div className="editor-tabs">
              <button className="is-active" type="button">
                <FileTypeIcon language={activeFile.language} />
                {activeFile.name}
                {activeFile.status && <i />}
              </button>
              <div className="editor-mode-switch" aria-label="Editor view">
                <button
                  className={editorMode === "source" ? "is-active" : ""}
                  type="button"
                  onClick={() => setEditorMode("source")}
                >
                  Source
                </button>
                <button
                  className={editorMode === "diff" ? "is-active" : ""}
                  disabled={!activeFile.originalContent}
                  type="button"
                  onClick={() => setEditorMode("diff")}
                >
                  Diff
                </button>
              </div>
            </div>

            <div className="editor-surface">
              {editorMode === "diff" && activeFile.originalContent ? (
                <MonacoDiffEditor
                  language={activeFile.language}
                  modified={activeFile.content}
                  original={activeFile.originalContent}
                  options={{
                    ...editorOptions,
                    renderSideBySide: false,
                    readOnly: true,
                  }}
                  theme="vs-dark"
                />
              ) : (
                <MonacoEditor
                  language={activeFile.language}
                  onMount={(editor) => {
                    editorRef.current = editor;
                    if (selectedNode?.filePath === activeFile.path) {
                      editor.revealLineInCenter(selectedNode.line);
                      editor.setPosition({
                        lineNumber: selectedNode.line,
                        column: 1,
                      });
                    }
                  }}
                  options={editorOptions}
                  path={activeFile.path}
                  theme="vs-dark"
                  value={activeFile.content}
                />
              )}
            </div>
            <footer className="editor-statusbar">
              <span>{activeFile.language}</span>
              <span>UTF-8</span>
              {selectedNode && selectedNode.filePath === activeFile.path && (
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
              <strong>Query Engine · 6 visible nodes</strong>
            </div>
            <span>graph.json</span>
          </header>
          <ArchitectureGraph
            activeFilePath={activeFilePath}
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
                    <span>Query Engine · 6 nodes · 5 edges</span>
                  </div>
                </div>

                {messages.map((message) => (
                  <article
                    className={`agent-message is-${message.role}`}
                    key={message.id}
                  >
                    <span>{message.role === "assistant" ? "Graphify" : "You"}</span>
                    <p>{message.content}</p>
                  </article>
                ))}

                {isStreaming && (
                  <article
                    className="agent-message is-assistant is-streaming"
                    role="status"
                  >
                    <span>Graphify</span>
                    <p>
                      Tracing graph relationships
                      <i />
                      <i />
                      <i />
                    </p>
                  </article>
                )}

                <section className="agent-change-card">
                  <header>
                    <div>
                      <span>Proposed changes</span>
                      <strong>{changedFiles.length} files</strong>
                    </div>
                    <span>+18 −4</span>
                  </header>
                  <ul>
                    {changedFiles.map((file) => (
                      <li key={file.path}>
                        <FileTypeIcon language={file.language} />
                        <span>{file.path}</span>
                        <i>{file.status}</i>
                      </li>
                    ))}
                  </ul>
                  <div>
                    <button type="button" onClick={inspectDiff}>
                      Inspect Diff
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setPrompt(
                          "Prepare a pull request summary for the proposed changes.",
                        );
                      }}
                    >
                      Prepare Pull Request
                    </button>
                  </div>
                </section>
              </div>

              <div className="agent-suggestions" aria-label="Suggested queries">
                {SUGGESTED_PROMPTS.map((suggestion) => (
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
                  <span>Graph-aware context enabled</span>
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
                      disabled={!prompt.trim()}
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
                  <option value="tool">Tools</option>
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
    </main>
  );
}
