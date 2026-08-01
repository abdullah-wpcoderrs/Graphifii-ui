"use client";

import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  type Edge,
  type Node,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo, useState } from "react";
import type { WorkspaceGraphEdge, WorkspaceGraphNode } from "../lib/graph";

type ArchitectureGraphProps = {
  nodes: WorkspaceGraphNode[];
  edges: WorkspaceGraphEdge[];
  activeFilePath: string;
  onSelectNode: (node: WorkspaceGraphNode) => void;
  selectedNodeId: string | null;
};

export default function ArchitectureGraph({
  nodes: graphNodes,
  edges: graphEdges,
  activeFilePath,
  onSelectNode,
  selectedNodeId,
}: ArchitectureGraphProps) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<"all" | string>("all");
  const [community, setCommunity] = useState("all");
  const [showEdges, setShowEdges] = useState(true);

  const kinds = useMemo(
    () => Array.from(new Set(graphNodes.map((node) => node.kind))).sort(),
    [graphNodes],
  );

  const communities = useMemo(
    () => Array.from(new Set(graphNodes.map((node) => node.community))).sort(),
    [graphNodes],
  );

  const visibleGraphNodes = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return graphNodes.filter((node) => {
      const matchesQuery =
        !normalizedQuery ||
        node.label.toLocaleLowerCase().includes(normalizedQuery) ||
        node.filePath.toLocaleLowerCase().includes(normalizedQuery);
      const matchesKind = kind === "all" || node.kind === kind;
      const matchesCommunity =
        community === "all" || node.community === community;
      return matchesQuery && matchesKind && matchesCommunity;
    });
  }, [community, graphNodes, kind, query]);

  const visibleIds = useMemo(
    () => new Set(visibleGraphNodes.map((node) => node.id)),
    [visibleGraphNodes],
  );

  const nodes = useMemo<Node[]>(
    () =>
      visibleGraphNodes.map((node) => {
        const isSelected = selectedNodeId === node.id;
        const matchesFile = Boolean(activeFilePath) && activeFilePath === node.filePath;
        const isGodNode = node.centrality === "god";

        return {
          id: node.id,
          position: { x: node.x, y: node.y },
          data: {
            label: (
              <div className="graph-node-content">
                <span>{node.kind}</span>
                <strong>{node.label}</strong>
                <code>{node.filePath || node.id}</code>
              </div>
            ),
          },
          className: [
            "graph-node",
            isGodNode ? "is-god-node" : "",
            isSelected ? "is-selected" : "",
            matchesFile ? "matches-file" : "",
          ]
            .filter(Boolean)
            .join(" "),
          style: {
            width: 154,
          },
        };
      }),
    [activeFilePath, selectedNodeId, visibleGraphNodes],
  );

  const edges = useMemo<Edge[]>(
    () =>
      showEdges
        ? graphEdges
            .filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target))
            .map((edge) => ({
              ...edge,
              animated: edge.source === selectedNodeId,
              markerEnd: { type: MarkerType.ArrowClosed },
              className: "graph-edge",
              labelStyle: { fill: "#71717a", fontSize: 8 },
              style: { stroke: "#3f3f46", strokeWidth: 1.2 },
            }))
        : [],
    [graphEdges, selectedNodeId, showEdges, visibleIds],
  );

  const handleNodeClick: NodeMouseHandler = (_, flowNode) => {
    const sourceNode = graphNodes.find((node) => node.id === flowNode.id);
    if (sourceNode) onSelectNode(sourceNode);
  };

  const selectedNode = graphNodes.find((node) => node.id === selectedNodeId);

  return (
    <div className="architecture-graph">
      <div className="graph-toolbar">
        <label className="graph-search">
          <span className="sr-only">Search architecture graph</span>
          <svg aria-hidden="true" viewBox="0 0 20 20">
            <circle cx="8.5" cy="8.5" r="5.5" />
            <path d="m12.5 12.5 4 4" />
          </svg>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search nodes"
            type="search"
          />
        </label>
        <select
          aria-label="Filter graph by node type"
          value={kind}
          onChange={(event) => setKind(event.target.value)}
        >
          <option value="all">All types</option>
          {kinds.map((item) => (
            <option value={item} key={item}>
              {item}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter graph by community"
          value={community}
          onChange={(event) => setCommunity(event.target.value)}
        >
          <option value="all">All communities</option>
          {communities.map((item) => (
            <option value={item} key={item}>
              {item}
            </option>
          ))}
        </select>
        <button
          className={showEdges ? "is-active" : ""}
          type="button"
          onClick={() => setShowEdges((value) => !value)}
        >
          Edges
        </button>
      </div>

      <div className="graph-canvas">
        {nodes.length > 0 ? (
          <ReactFlow
            colorMode="dark"
            edges={edges}
            fitView
            fitViewOptions={{ padding: 0.24 }}
            minZoom={0.35}
            nodes={nodes}
            nodesDraggable
            nodesConnectable={false}
            onNodeClick={handleNodeClick}
            proOptions={{ hideAttribution: true }}
          >
            <Background
              color="#27272a"
              gap={22}
              size={1}
              variant={BackgroundVariant.Dots}
            />
            <MiniMap
              className="graph-minimap"
              maskColor="rgb(9 9 11 / 72%)"
              nodeColor={(node) =>
                node.className?.includes("is-god-node") ? "#8b5cf6" : "#3f3f46"
              }
              pannable
              zoomable
            />
            <Controls className="graph-controls" showInteractive={false} />
          </ReactFlow>
        ) : (
          <div className="graph-empty">
            <strong>No graph nodes match.</strong>
            <p>Clear a search or filter to restore the architecture view.</p>
            <button
              type="button"
              onClick={() => {
                setQuery("");
                setKind("all");
                setCommunity("all");
              }}
            >
              Reset graph filters
            </button>
          </div>
        )}
      </div>

      {selectedNode && (
        <aside className="graph-inspector" aria-label="Selected graph node">
          <div>
            <span>{selectedNode.kind}</span>
            <strong>{selectedNode.label}</strong>
          </div>
          <dl>
            <div>
              <dt>Community</dt>
              <dd>{selectedNode.community}</dd>
            </div>
            <div>
              <dt>Source</dt>
              <dd>
                {selectedNode.filePath || "unknown"}
                {selectedNode.filePath ? `:${selectedNode.line}` : ""}
              </dd>
            </div>
          </dl>
        </aside>
      )}
    </div>
  );
}
