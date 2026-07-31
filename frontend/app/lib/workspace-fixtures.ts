export type ProvisioningPhase = {
  id:
    | "sandbox"
    | "clone"
    | "languages"
    | "parse"
    | "relationships"
    | "persist"
    | "workspace";
  label: string;
  description: string;
  progress: number;
  event: string;
};

export type WorkspaceFile = {
  path: string;
  name: string;
  language: string;
  content: string;
  originalContent?: string;
  status?: "modified" | "new" | "renamed";
};

export type WorkspaceGraphNode = {
  id: string;
  label: string;
  kind: "module" | "class" | "function";
  filePath: string;
  line: number;
  community: string;
  centrality: "standard" | "god";
  x: number;
  y: number;
};

export type WorkspaceGraphEdge = {
  id: string;
  source: string;
  target: string;
  label?: string;
};

export type AgentMessage = {
  id: string;
  role: "assistant" | "user";
  content: string;
};

export const PROVISIONING_PHASES: ProvisioningPhase[] = [
  {
    id: "sandbox",
    label: "Creating sandbox",
    description: "Allocating isolated compute and a temporary workspace volume.",
    progress: 8,
    event: "Sandbox graphify-ws-8fa2 allocated in eu-west.",
  },
  {
    id: "clone",
    label: "Cloning repository",
    description: "Fetching the selected branch with GitHub App credentials.",
    progress: 22,
    event: "Cloned Graphify-Labs/graphify at main (depth 1).",
  },
  {
    id: "languages",
    label: "Detecting languages",
    description: "Inspecting source files and selecting structural parsers.",
    progress: 34,
    event: "Detected Python, TypeScript, Markdown, and Dockerfile sources.",
  },
  {
    id: "parse",
    label: "Parsing source files",
    description: "Extracting symbols, imports, calls, and source locations.",
    progress: 58,
    event: "Parsed 1,842 source files and 9,416 symbols.",
  },
  {
    id: "relationships",
    label: "Building relationships and communities",
    description: "Linking dependencies and calculating graph communities.",
    progress: 76,
    event: "Built 18,292 edges across 14 detected communities.",
  },
  {
    id: "persist",
    label: "Persisting graph artifacts",
    description: "Saving graph.json, reports, and reusable extraction state.",
    progress: 91,
    event: "Persisted graph.json and GRAPH_REPORT.md.",
  },
  {
    id: "workspace",
    label: "Preparing workspace",
    description: "Restoring editor state and connecting the graph-aware agent.",
    progress: 100,
    event: "Workspace ready. Opening the Graphify IDE.",
  },
];

export const WORKSPACE_FILES: WorkspaceFile[] = [
  {
    path: "graphify/query.py",
    name: "query.py",
    language: "python",
    status: "modified",
    originalContent: `from pathlib import Path

def query_graph(graph_path: Path, question: str):
    graph = load_graph(graph_path)
    nodes = match_nodes(graph, question)
    return traverse(graph, nodes)
`,
    content: `from pathlib import Path
from collections.abc import Iterable

def query_graph(
    graph_path: Path,
    question: str,
    *,
    max_depth: int = 3,
) -> dict:
    """Return a bounded, explainable subgraph for a question."""
    graph = load_graph(graph_path)
    nodes: Iterable[GraphNode] = match_nodes(graph, question)

    return traverse(
        graph,
        nodes,
        max_depth=max_depth,
        include_evidence=True,
    )
`,
  },
  {
    path: "graphify/extract.py",
    name: "extract.py",
    language: "python",
    content: `from collections.abc import Callable

ProgressCallback = Callable[[int, str], None]

def extract_codebase(
    target_dir: str,
    progress_callback: ProgressCallback | None = None,
):
    files = collect_files(target_dir)
    for index, file_path in enumerate(files):
        extract_file(file_path)
        if progress_callback:
            progress_callback(index + 1, file_path)
`,
  },
  {
    path: "graphify/graph.py",
    name: "graph.py",
    language: "python",
    status: "modified",
    originalContent: `class KnowledgeGraph:
    def add_node(self, node):
        self.nodes[node.id] = node
`,
    content: `class KnowledgeGraph:
    def add_node(self, node: GraphNode) -> None:
        self.nodes[node.id] = node

    def neighbors(self, node_id: str) -> list[GraphNode]:
        return [
            self.nodes[edge.target]
            for edge in self.edges
            if edge.source == node_id
        ]
`,
  },
  {
    path: "server/app.py",
    name: "app.py",
    language: "python",
    content: `from fastapi import FastAPI
from graphify.query import query_graph

app = FastAPI(title="Graphify Sidecar")

@app.get("/health")
def health():
    return {"status": "ok"}
`,
  },
  {
    path: "server/ws_manager.py",
    name: "ws_manager.py",
    language: "python",
    status: "new",
    content: `class ConnectionManager:
    def __init__(self) -> None:
        self.connections = set()

    async def broadcast(self, event: dict) -> None:
        for connection in self.connections:
            await connection.send_json(event)
`,
  },
  {
    path: "README.md",
    name: "README.md",
    language: "markdown",
    content: `# Graphify

Build a navigable structural knowledge graph from a codebase.

## Cloud workspace

The sidecar exposes extraction and query operations to the Graphify UI.
`,
  },
];

export const WORKSPACE_GRAPH_NODES: WorkspaceGraphNode[] = [
  {
    id: "query_graph",
    label: "query_graph",
    kind: "function",
    filePath: "graphify/query.py",
    line: 4,
    community: "Query Engine",
    centrality: "god",
    x: 380,
    y: 180,
  },
  {
    id: "knowledge_graph",
    label: "KnowledgeGraph",
    kind: "class",
    filePath: "graphify/graph.py",
    line: 1,
    community: "Graph Core",
    centrality: "god",
    x: 100,
    y: 270,
  },
  {
    id: "extract_codebase",
    label: "extract_codebase",
    kind: "function",
    filePath: "graphify/extract.py",
    line: 5,
    community: "Extraction",
    centrality: "standard",
    x: 110,
    y: 70,
  },
  {
    id: "sidecar_app",
    label: "FastAPI sidecar",
    kind: "module",
    filePath: "server/app.py",
    line: 1,
    community: "Cloud API",
    centrality: "standard",
    x: 650,
    y: 70,
  },
  {
    id: "ws_manager",
    label: "ConnectionManager",
    kind: "class",
    filePath: "server/ws_manager.py",
    line: 1,
    community: "Cloud API",
    centrality: "standard",
    x: 660,
    y: 300,
  },
  {
    id: "match_nodes",
    label: "match_nodes",
    kind: "function",
    filePath: "graphify/query.py",
    line: 13,
    community: "Query Engine",
    centrality: "standard",
    x: 380,
    y: 390,
  },
];

export const WORKSPACE_GRAPH_EDGES: WorkspaceGraphEdge[] = [
  { id: "e1", source: "sidecar_app", target: "query_graph", label: "calls" },
  {
    id: "e2",
    source: "query_graph",
    target: "knowledge_graph",
    label: "reads",
  },
  {
    id: "e3",
    source: "query_graph",
    target: "match_nodes",
    label: "calls",
  },
  {
    id: "e4",
    source: "extract_codebase",
    target: "knowledge_graph",
    label: "writes",
  },
  {
    id: "e5",
    source: "ws_manager",
    target: "extract_codebase",
    label: "reports",
  },
];

export const INITIAL_AGENT_MESSAGES: AgentMessage[] = [
  {
    id: "assistant-1",
    role: "assistant",
    content:
      "The graph is ready. I can trace dependencies, explain high-centrality nodes, or prepare a reviewable change.",
  },
  {
    id: "user-1",
    role: "user",
    content: "Make graph queries bounded and include evidence in the response.",
  },
  {
    id: "assistant-2",
    role: "assistant",
    content:
      "I updated query_graph with a bounded max_depth option and evidence-aware traversal. Two files are modified; no branch has been pushed.",
  },
];

export const OUTPUT_LOGS = [
  { time: "14:32:08", tone: "info", message: "Workspace restored from snapshot." },
  { time: "14:32:09", tone: "success", message: "graph.json loaded · 9,416 nodes." },
  { time: "14:32:09", tone: "success", message: "18,292 directed edges indexed." },
  { time: "14:32:11", tone: "info", message: "Agent context attached to Query Engine community." },
  { time: "14:33:02", tone: "tool", message: "query_graph(\"bounded traversal evidence\")" },
  { time: "14:33:04", tone: "success", message: "Patch proposal created for 2 files." },
];
