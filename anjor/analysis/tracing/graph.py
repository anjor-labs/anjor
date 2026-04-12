"""TraceGraph — DAG reconstruction from AgentSpanEvent records.

Pure module: no I/O, no async, no framework dependencies.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass
class SpanNode:
    """A single node in the trace DAG."""

    span_id: str
    parent_span_id: str | None
    agent_name: str
    span_kind: str
    status: str
    token_input: int
    token_output: int
    tool_calls_count: int
    llm_calls_count: int
    started_at: str
    ended_at: str | None
    # Computed when the graph is built
    depth: int = 0

    @property
    def duration_ms(self) -> float | None:
        """Wall-clock duration in ms, or None if the span has not ended."""
        if not self.started_at or not self.ended_at:
            return None
        from datetime import datetime

        try:
            start = datetime.fromisoformat(self.started_at)
            end = datetime.fromisoformat(self.ended_at)
            return (end - start).total_seconds() * 1000
        except Exception:
            return None


class TraceGraph:
    """DAG of agent spans reconstructed from raw span records.

    Usage::

        graph = TraceGraph.build(spans)
        for node in graph.topological_order():
            print(node.agent_name, node.depth)
    """

    def __init__(self) -> None:
        self._nodes: dict[str, SpanNode] = {}
        # adjacency list: parent_id → [child_id, ...]
        self._children: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def build(cls, spans: list[dict[str, Any]]) -> TraceGraph:
        """Build a TraceGraph from a list of raw span dicts."""
        graph = cls()
        for span in spans:
            node = SpanNode(
                span_id=span.get("span_id", ""),
                parent_span_id=span.get("parent_span_id"),
                agent_name=span.get("agent_name", "unknown"),
                span_kind=span.get("span_kind", "root"),
                status=span.get("status", "ok"),
                token_input=int(span.get("token_input", 0)),
                token_output=int(span.get("token_output", 0)),
                tool_calls_count=int(span.get("tool_calls_count", 0)),
                llm_calls_count=int(span.get("llm_calls_count", 0)),
                started_at=span.get("started_at", ""),
                ended_at=span.get("ended_at"),
            )
            if node.span_id:
                graph._nodes[node.span_id] = node

        # Build adjacency list
        for node in graph._nodes.values():
            if node.parent_span_id and node.parent_span_id in graph._nodes:
                graph._children.setdefault(node.parent_span_id, []).append(node.span_id)

        # Compute depths via BFS from roots
        for root in graph.roots():
            queue: deque[tuple[str, int]] = deque([(root.span_id, 0)])
            while queue:
                sid, depth = queue.popleft()
                graph._nodes[sid].depth = depth
                for child_id in graph._children.get(sid, []):
                    queue.append((child_id, depth + 1))

        return graph

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def nodes(self) -> list[SpanNode]:
        """All nodes in insertion order."""
        return list(self._nodes.values())

    def edges(self) -> list[tuple[str, str]]:
        """All (parent_id, child_id) pairs."""
        result = []
        for parent_id, children in self._children.items():
            for child_id in children:
                result.append((parent_id, child_id))
        return result

    def roots(self) -> list[SpanNode]:
        """Spans with no parent (or whose parent is not in this graph)."""
        return [
            n
            for n in self._nodes.values()
            if n.parent_span_id is None or n.parent_span_id not in self._nodes
        ]

    def children(self, span_id: str) -> list[SpanNode]:
        """Direct children of the given span."""
        return [self._nodes[sid] for sid in self._children.get(span_id, [])]

    def has_cycle(self) -> bool:
        """True if the graph contains a cycle (should never happen in practice)."""
        return len(self.topological_order()) < len(self._nodes)

    def topological_order(self) -> list[SpanNode]:
        """Kahn's algorithm — returns nodes in topological order.

        Returns a partial list if a cycle exists (len < total nodes).
        """
        # in-degree count
        in_degree: dict[str, int] = dict.fromkeys(self._nodes, 0)
        for parent_id, children in self._children.items():
            if parent_id not in in_degree:
                continue
            for child_id in children:
                if child_id in in_degree:
                    in_degree[child_id] += 1

        queue: deque[str] = deque(sid for sid, deg in in_degree.items() if deg == 0)
        order: list[SpanNode] = []

        while queue:
            sid = queue.popleft()
            order.append(self._nodes[sid])
            for child_id in self._children.get(sid, []):
                if child_id not in in_degree:
                    continue
                in_degree[child_id] -= 1
                if in_degree[child_id] == 0:
                    queue.append(child_id)

        return order

    def to_adjacency_list(self) -> dict[str, list[str]]:
        """Return the adjacency list as a plain dict (span_id → [child_ids])."""
        return {k: list(v) for k, v in self._children.items()}
