"""Unit tests for TraceGraph — DAG reconstruction and queries."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from anjor.analysis.tracing.graph import TraceGraph

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_span(
    span_id: str | None = None,
    parent_span_id: str | None = None,
    agent_name: str = "agent",
    span_kind: str = "root",
    status: str = "ok",
    token_input: int = 100,
    token_output: int = 50,
    tool_calls_count: int = 1,
    llm_calls_count: int = 1,
    started_at: str = "2026-04-12T10:00:00.000000+00:00",
    ended_at: str | None = "2026-04-12T10:00:01.000000+00:00",
) -> dict:
    return {
        "span_id": span_id or str(uuid.uuid4()),
        "parent_span_id": parent_span_id,
        "agent_name": agent_name,
        "span_kind": span_kind,
        "status": status,
        "token_input": token_input,
        "token_output": token_output,
        "tool_calls_count": tool_calls_count,
        "llm_calls_count": llm_calls_count,
        "started_at": started_at,
        "ended_at": ended_at,
    }


# ---------------------------------------------------------------------------
# Empty and single-node graphs
# ---------------------------------------------------------------------------


class TestEmptyGraph:
    def test_empty_nodes(self) -> None:
        g = TraceGraph.build([])
        assert g.nodes() == []

    def test_empty_edges(self) -> None:
        g = TraceGraph.build([])
        assert g.edges() == []

    def test_empty_roots(self) -> None:
        g = TraceGraph.build([])
        assert g.roots() == []

    def test_empty_topological(self) -> None:
        g = TraceGraph.build([])
        assert g.topological_order() == []

    def test_empty_no_cycle(self) -> None:
        g = TraceGraph.build([])
        assert g.has_cycle() is False


class TestSingleNode:
    def test_single_root(self) -> None:
        span = make_span(span_kind="root")
        g = TraceGraph.build([span])
        assert len(g.nodes()) == 1
        assert len(g.roots()) == 1
        assert g.roots()[0].span_id == span["span_id"]

    def test_single_node_depth_zero(self) -> None:
        span = make_span()
        g = TraceGraph.build([span])
        assert g.nodes()[0].depth == 0

    def test_single_node_no_cycle(self) -> None:
        g = TraceGraph.build([make_span()])
        assert g.has_cycle() is False

    def test_single_node_topological(self) -> None:
        span = make_span()
        g = TraceGraph.build([span])
        order = g.topological_order()
        assert len(order) == 1
        assert order[0].span_id == span["span_id"]


# ---------------------------------------------------------------------------
# Linear chain
# ---------------------------------------------------------------------------


class TestLinearChain:
    def _build_chain(self, length: int) -> tuple[TraceGraph, list[dict]]:
        spans = []
        prev_id = None
        for i in range(length):
            s = make_span(
                agent_name=f"agent_{i}",
                span_kind="root" if i == 0 else "subagent",
                parent_span_id=prev_id,
            )
            spans.append(s)
            prev_id = s["span_id"]
        return TraceGraph.build(spans), spans

    def test_chain_node_count(self) -> None:
        g, spans = self._build_chain(4)
        assert len(g.nodes()) == 4

    def test_chain_edge_count(self) -> None:
        g, spans = self._build_chain(4)
        assert len(g.edges()) == 3

    def test_chain_single_root(self) -> None:
        g, spans = self._build_chain(4)
        assert len(g.roots()) == 1
        assert g.roots()[0].span_id == spans[0]["span_id"]

    def test_chain_topological_order(self) -> None:
        g, spans = self._build_chain(4)
        order = g.topological_order()
        assert [n.agent_name for n in order] == ["agent_0", "agent_1", "agent_2", "agent_3"]

    def test_chain_depths(self) -> None:
        g, spans = self._build_chain(4)
        g.topological_order()  # ensure depths computed
        depths = {n.agent_name: n.depth for n in g.nodes()}
        assert depths == {"agent_0": 0, "agent_1": 1, "agent_2": 2, "agent_3": 3}

    def test_chain_no_cycle(self) -> None:
        g, _ = self._build_chain(5)
        assert g.has_cycle() is False


# ---------------------------------------------------------------------------
# Fan-out (one orchestrator → N subagents)
# ---------------------------------------------------------------------------


class TestFanOut:
    def _build_fanout(self, n: int) -> tuple[TraceGraph, dict, list[dict]]:
        root = make_span(agent_name="orchestrator", span_kind="orchestrator")
        children = [
            make_span(
                agent_name=f"worker_{i}",
                span_kind="subagent",
                parent_span_id=root["span_id"],
            )
            for i in range(n)
        ]
        return TraceGraph.build([root] + children), root, children

    def test_fanout_roots(self) -> None:
        g, root, _ = self._build_fanout(3)
        assert len(g.roots()) == 1
        assert g.roots()[0].span_id == root["span_id"]

    def test_fanout_children(self) -> None:
        g, root, children = self._build_fanout(3)
        child_nodes = g.children(root["span_id"])
        assert len(child_nodes) == 3
        child_names = {n.agent_name for n in child_nodes}
        assert child_names == {"worker_0", "worker_1", "worker_2"}

    def test_fanout_child_depths(self) -> None:
        g, root, children = self._build_fanout(3)
        for child in g.children(root["span_id"]):
            assert child.depth == 1

    def test_fanout_edges(self) -> None:
        g, root, children = self._build_fanout(3)
        assert len(g.edges()) == 3

    def test_fanout_topological_root_first(self) -> None:
        g, root, _ = self._build_fanout(4)
        order = g.topological_order()
        assert order[0].span_id == root["span_id"]

    def test_fanout_no_cycle(self) -> None:
        g, _, _ = self._build_fanout(5)
        assert g.has_cycle() is False


# ---------------------------------------------------------------------------
# Fan-in (N parents → one aggregator)
# ---------------------------------------------------------------------------


class TestFanIn:
    def test_fanin_multiple_roots(self) -> None:
        # Two roots whose child has both as notional parents — but in our model
        # each span has one parent_span_id, so we model "fan-in" as an aggregator
        # that lists one parent (real DAG fan-in needs multi-parent support;
        # for now we just verify roots are correctly identified)
        a = make_span(agent_name="source_a", span_kind="root")
        b = make_span(agent_name="source_b", span_kind="root")
        # aggregator references only one parent — still valid graph
        agg = make_span(
            agent_name="aggregator",
            span_kind="subagent",
            parent_span_id=a["span_id"],
        )
        g = TraceGraph.build([a, b, agg])
        roots = {n.agent_name for n in g.roots()}
        assert "source_a" in roots
        assert "source_b" in roots

    def test_independent_roots(self) -> None:
        spans = [make_span(agent_name=f"root_{i}") for i in range(3)]
        g = TraceGraph.build(spans)
        assert len(g.roots()) == 3


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    def test_two_node_cycle(self) -> None:
        a_id = str(uuid.uuid4())
        b_id = str(uuid.uuid4())
        a = make_span(span_id=a_id, parent_span_id=b_id, agent_name="a")
        b = make_span(span_id=b_id, parent_span_id=a_id, agent_name="b")
        g = TraceGraph.build([a, b])
        assert g.has_cycle() is True

    def test_three_node_cycle(self) -> None:
        a_id, b_id, c_id = (str(uuid.uuid4()) for _ in range(3))
        spans = [
            make_span(span_id=a_id, parent_span_id=c_id),
            make_span(span_id=b_id, parent_span_id=a_id),
            make_span(span_id=c_id, parent_span_id=b_id),
        ]
        g = TraceGraph.build(spans)
        assert g.has_cycle() is True

    def test_no_cycle_linear(self) -> None:
        a_id = str(uuid.uuid4())
        b_id = str(uuid.uuid4())
        a = make_span(span_id=a_id)
        b = make_span(span_id=b_id, parent_span_id=a_id)
        g = TraceGraph.build([a, b])
        assert g.has_cycle() is False


# ---------------------------------------------------------------------------
# SpanNode properties
# ---------------------------------------------------------------------------


class TestSpanNode:
    def test_duration_ms_computed(self) -> None:
        span = make_span(
            started_at="2026-04-12T10:00:00.000000+00:00",
            ended_at="2026-04-12T10:00:02.500000+00:00",
        )
        g = TraceGraph.build([span])
        node = g.nodes()[0]
        assert node.duration_ms == pytest.approx(2500.0, abs=1.0)

    def test_duration_ms_none_when_not_ended(self) -> None:
        span = make_span(ended_at=None)
        g = TraceGraph.build([span])
        assert g.nodes()[0].duration_ms is None


# ---------------------------------------------------------------------------
# Adjacency list
# ---------------------------------------------------------------------------


class TestAdjacencyList:
    def test_adjacency_list_structure(self) -> None:
        root = make_span()
        child = make_span(parent_span_id=root["span_id"])
        g = TraceGraph.build([root, child])
        adj = g.to_adjacency_list()
        assert root["span_id"] in adj
        assert child["span_id"] in adj[root["span_id"]]

    def test_leaf_not_in_adjacency_list(self) -> None:
        root = make_span()
        child = make_span(parent_span_id=root["span_id"])
        g = TraceGraph.build([root, child])
        adj = g.to_adjacency_list()
        assert child["span_id"] not in adj


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------


def _build_random_dag(draw: Any, max_nodes: int = 8) -> list[dict]:
    """Draw a random DAG — each node references only a previous node as parent."""
    n = draw(st.integers(min_value=1, max_value=max_nodes))
    ids = [str(uuid.uuid4()) for _ in range(n)]
    spans = []
    for i, sid in enumerate(ids):
        parent = draw(st.sampled_from(ids[:i])) if i > 0 and draw(st.booleans()) else None
        spans.append(make_span(span_id=sid, parent_span_id=parent))
    return spans


@given(st.data())
@settings(max_examples=100)
def test_random_dag_never_has_cycle(data: Any) -> None:
    spans = _build_random_dag(data.draw)
    g = TraceGraph.build(spans)
    assert g.has_cycle() is False


@given(st.data())
@settings(max_examples=100)
def test_topological_order_covers_all_nodes(data: Any) -> None:
    spans = _build_random_dag(data.draw)
    g = TraceGraph.build(spans)
    assert len(g.topological_order()) == len(g.nodes())


@given(st.data())
@settings(max_examples=100)
def test_topological_order_respects_parent_before_child(data: Any) -> None:
    spans = _build_random_dag(data.draw)
    g = TraceGraph.build(spans)
    order = g.topological_order()
    position = {n.span_id: i for i, n in enumerate(order)}
    for node in order:
        if node.parent_span_id and node.parent_span_id in position:
            assert position[node.parent_span_id] < position[node.span_id]
