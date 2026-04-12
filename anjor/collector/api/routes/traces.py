"""GET /traces and GET /traces/{trace_id}/graph — multi-agent trace endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from anjor.analysis.tracing.graph import TraceGraph
from anjor.collector.api.schemas import SpanNodeItem, TraceGraphResponse, TraceSummaryItem

if TYPE_CHECKING:
    from anjor.collector.service import CollectorService


def make_traces_router(service: CollectorService) -> APIRouter:
    router = APIRouter()

    @router.get("/traces", response_model=list[TraceSummaryItem])
    async def list_traces(limit: int = 50, offset: int = 0) -> list[TraceSummaryItem]:
        """List all traces with summary stats, newest first."""
        summaries = await service.storage.list_traces(limit=limit, offset=offset)
        return [
            TraceSummaryItem(
                trace_id=s.trace_id,
                root_agent_name=s.root_agent_name,
                span_count=s.span_count,
                total_token_input=s.total_token_input,
                total_token_output=s.total_token_output,
                started_at=s.started_at,
                status=s.status,
            )
            for s in summaries
        ]

    @router.get("/traces/{trace_id}/graph", response_model=TraceGraphResponse)
    async def get_trace_graph(trace_id: str) -> TraceGraphResponse:
        """Return the full DAG for a trace as nodes + edges."""
        spans = await service.storage.query_spans(trace_id)
        if not spans:
            raise HTTPException(status_code=404, detail=f"Trace {trace_id!r} not found.")

        graph = TraceGraph.build(spans)
        nodes = [
            SpanNodeItem(
                span_id=n.span_id,
                parent_span_id=n.parent_span_id,
                agent_name=n.agent_name,
                span_kind=n.span_kind,
                depth=n.depth,
                status=n.status,
                token_input=n.token_input,
                token_output=n.token_output,
                tool_calls_count=n.tool_calls_count,
                llm_calls_count=n.llm_calls_count,
                started_at=n.started_at,
                ended_at=n.ended_at,
                duration_ms=n.duration_ms,
            )
            for n in graph.topological_order()
        ]
        return TraceGraphResponse(
            trace_id=trace_id,
            node_count=len(graph.nodes()),
            has_cycle=graph.has_cycle(),
            nodes=nodes,
            edges=graph.edges(),
        )

    return router
