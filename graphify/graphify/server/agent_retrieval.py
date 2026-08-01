"""Graph-aware retrieval for agent questions.

Reuses graphify's existing `_query_graph_text` (lexical scoring → seed
selection → BFS/DFS walk → token-budgeted text) rather than reimplementing
retrieval. That function is imported and called in-process, not shelled out
to the CLI: it takes an already-loaded networkx graph and returns a string,
so a subprocess would add a process spawn and a second graph parse to get
the identical result. (The sandbox shells out to `graphify update` because
extraction genuinely needs the CLI's whole pipeline; this does not.)

Retrieval costs no LLM tokens — it is pure graph traversal. Its output
becomes part of the prompt, which is why the token budget matters: it is
the single biggest lever on what each agent call costs.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from pathlib import Path

import httpx
import networkx as nx

logger = logging.getLogger("graphify.server.agent_retrieval")

_FETCH_TIMEOUT = 15.0

# Context sent to the model per question. Large enough to carry real
# structure, small enough that a big repo cannot blow up the prompt.
DEFAULT_TOKEN_BUDGET = 3000

# Parsing a graph is the expensive part of answering a question, and a
# conversation asks many questions against the same one. Bounded so a busy
# server holding many projects' graphs cannot grow without limit.
_CACHE_MAX_ENTRIES = 8
_graph_cache: OrderedDict[str, nx.Graph] = OrderedDict()


class RetrievalError(Exception):
    """The project's graph could not be loaded or queried."""


async def _fetch_graph_json(location: str) -> dict:
    if location.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as client:
            try:
                response = await client.get(location)
            except httpx.HTTPError as exc:
                raise RetrievalError(f"could not fetch the project graph: {exc}") from exc
        if response.status_code != 200:
            raise RetrievalError("the project graph is not available")
        return response.json()

    path = Path(location)
    if not path.is_file():
        raise RetrievalError("the project graph is not available")
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RetrievalError(f"could not read the project graph: {exc}") from exc


async def load_graph(location: str, *, cache_key: str) -> nx.Graph:
    """Load a project's graph.json into networkx, memoized per project.

    `edges="links"` is required, not optional: graphify writes node-link JSON
    where connections live under `links`. Loading without it yields a graph
    with every node and no edges, which retrieval would answer from silently
    and wrongly.
    """
    cached = _graph_cache.get(cache_key)
    if cached is not None:
        _graph_cache.move_to_end(cache_key)
        return cached

    data = await _fetch_graph_json(location)
    try:
        graph = nx.node_link_graph(data, edges="links")
    except Exception as exc:  # networkx raises a variety of shapes here
        raise RetrievalError(f"the project graph could not be parsed: {exc}") from exc

    _graph_cache[cache_key] = graph
    _graph_cache.move_to_end(cache_key)
    while len(_graph_cache) > _CACHE_MAX_ENTRIES:
        _graph_cache.popitem(last=False)

    return graph


def invalidate_graph_cache(cache_key: str) -> None:
    """Drop a project's cached graph — call after a re-extraction."""
    _graph_cache.pop(cache_key, None)


async def retrieve_context(
    graph_location: str,
    question: str,
    *,
    cache_key: str,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> str:
    """Graph context relevant to `question`, as prompt-ready text."""
    graph = await load_graph(graph_location, cache_key=cache_key)

    try:
        from graphify.serve import _query_graph_text
    except Exception as exc:  # pragma: no cover - import-time environment issue
        raise RetrievalError("the graph query engine is unavailable") from exc

    try:
        return _query_graph_text(graph, question, mode="bfs", depth=3, token_budget=token_budget)
    except Exception as exc:
        logger.exception("graph retrieval failed")
        raise RetrievalError(f"graph retrieval failed: {exc}") from exc


def candidate_paths(context: str, known_files: list[str], *, limit: int = 6) -> list[str]:
    """File paths worth sending to the model in full, given retrieved context.

    Retrieval returns node names, many of which are (or embed) real file
    paths. Cross-referencing them against the project's actual file list
    keeps this honest — a node name that merely resembles a path never
    becomes a fetch against the provider API.
    """
    if not known_files:
        return []

    hits: list[str] = []
    lowered = context.lower()
    # Longest paths first: matching "src/app/main.py" should not be beaten by
    # a coincidental substring hit on "main.py".
    for path in sorted(known_files, key=len, reverse=True):
        if path.lower() in lowered and path not in hits:
            hits.append(path)
        if len(hits) >= limit:
            break
    return hits
