/**
 * Adapts the real graph.json / files.json artifacts (produced by the
 * sandbox — see graphify/graphify/export.py) into the shapes the workspace
 * UI renders. graph.json is networkx node-link JSON: connections live under
 * `links`, not `edges`, and node ids/community numbers are graphify's, not
 * UI-invented ones.
 */

export type WorkspaceGraphNode = {
  id: string;
  label: string;
  kind: string;
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

export type RawGraphNode = {
  id: string;
  label?: string;
  type?: string;
  source_file?: string;
  source_location?: string;
  community?: number | null;
  community_name?: string | null;
};

export type RawGraphLink = {
  source: string;
  target: string;
  relation?: string;
};

export type RawGraph = {
  directed?: boolean;
  nodes?: RawGraphNode[];
  links?: RawGraphLink[];
};

export type GraphView = {
  nodes: WorkspaceGraphNode[];
  edges: WorkspaceGraphEdge[];
  nodeCount: number;
  edgeCount: number;
  communityCount: number;
};

const GOD_NODE_PERCENTILE = 0.95; // top 5% of nodes by degree read as hubs
const NODE_COLUMN_WIDTH = 190;
const NODE_ROW_HEIGHT = 110;
const COMMUNITY_GAP = 60;

function parseLine(location: string | undefined): number {
  if (!location) return 1;
  const match = /(\d+)/.exec(location);
  return match ? Number(match[1]) : 1;
}

export function buildGraphView(raw: RawGraph): GraphView {
  const rawNodes = raw.nodes ?? [];
  const rawLinks = raw.links ?? [];

  const degree = new Map<string, number>();
  for (const link of rawLinks) {
    degree.set(link.source, (degree.get(link.source) ?? 0) + 1);
    degree.set(link.target, (degree.get(link.target) ?? 0) + 1);
  }

  const sortedDegrees = Array.from(degree.values()).sort((a, b) => a - b);
  const thresholdIndex = Math.floor(sortedDegrees.length * GOD_NODE_PERCENTILE);
  const godThreshold =
    sortedDegrees.length > 0
      ? sortedDegrees[Math.min(thresholdIndex, sortedDegrees.length - 1)]
      : Infinity;

  const byCommunity = new Map<string, RawGraphNode[]>();
  for (const node of rawNodes) {
    const community =
      node.community_name ??
      (node.community != null ? `Community ${node.community}` : "Ungrouped");
    const bucket = byCommunity.get(community) ?? [];
    bucket.push(node);
    byCommunity.set(community, bucket);
  }

  const nodes: WorkspaceGraphNode[] = [];
  let cursorX = 0;

  for (const [community, members] of byCommunity) {
    const columns = Math.max(1, Math.ceil(Math.sqrt(members.length)));
    members.forEach((node, index) => {
      const column = index % columns;
      const row = Math.floor(index / columns);
      const nodeDegree = degree.get(node.id) ?? 0;

      nodes.push({
        id: node.id,
        label: node.label ?? node.id,
        kind: node.type ?? "symbol",
        filePath: node.source_file ?? "",
        line: parseLine(node.source_location),
        community,
        centrality: nodeDegree > 1 && nodeDegree >= godThreshold ? "god" : "standard",
        x: cursorX + column * NODE_COLUMN_WIDTH,
        y: row * NODE_ROW_HEIGHT,
      });
    });
    cursorX += columns * NODE_COLUMN_WIDTH + COMMUNITY_GAP;
  }

  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges: WorkspaceGraphEdge[] = rawLinks
    .filter((link) => nodeIds.has(link.source) && nodeIds.has(link.target))
    .map((link, index) => ({
      id: `${link.source}->${link.target}#${index}`,
      source: link.source,
      target: link.target,
      label: link.relation,
    }));

  return {
    nodes,
    edges,
    nodeCount: nodes.length,
    edgeCount: edges.length,
    communityCount: byCommunity.size,
  };
}

export type WorkspaceFileEntry = {
  path: string;
  name: string;
  size: number;
  language: string;
};

export type WorkspaceFileGroup = {
  label: string;
  files: WorkspaceFileEntry[];
};

export type RawFileTree = {
  files?: { path: string; size: number }[];
  count?: number;
  truncated?: boolean;
};

const LANGUAGE_BY_EXTENSION: Record<string, string> = {
  py: "python",
  md: "markdown",
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  json: "json",
  yml: "yaml",
  yaml: "yaml",
  toml: "toml",
  rs: "rust",
  go: "go",
  rb: "ruby",
  java: "java",
  css: "css",
  html: "html",
};

function languageFromPath(path: string): string {
  const extension = path.split(".").pop()?.toLowerCase() ?? "";
  return LANGUAGE_BY_EXTENSION[extension] ?? "plaintext";
}

const MAX_RENDERED_FILES = 1000;

export function buildFileGroups(tree: RawFileTree): {
  groups: WorkspaceFileGroup[];
  totalFiles: number;
  renderedFiles: number;
  truncated: boolean;
} {
  const files = tree.files ?? [];
  const visible = files.slice(0, MAX_RENDERED_FILES);

  const groups = new Map<string, WorkspaceFileEntry[]>();
  for (const file of visible) {
    const slashIndex = file.path.indexOf("/");
    const top = slashIndex === -1 ? "(root)" : file.path.slice(0, slashIndex);
    const bucket = groups.get(top) ?? [];
    bucket.push({
      path: file.path,
      name: file.path.split("/").pop() ?? file.path,
      size: file.size,
      language: languageFromPath(file.path),
    });
    groups.set(top, bucket);
  }

  return {
    groups: Array.from(groups.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([label, groupFiles]) => ({
        label,
        files: groupFiles.sort((a, b) => a.name.localeCompare(b.name)),
      })),
    totalFiles: tree.count ?? files.length,
    renderedFiles: visible.length,
    truncated: Boolean(tree.truncated) || files.length > MAX_RENDERED_FILES,
  };
}
