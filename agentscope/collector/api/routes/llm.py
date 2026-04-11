"""GET /llm, GET /llm/trace/{trace_id} — LLM call query endpoints (Phase 2)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException

from agentscope.collector.api.schemas import LLMDetailItem, LLMSummaryItem
from agentscope.collector.storage.base import LLMQueryFilters

if TYPE_CHECKING:
    from agentscope.collector.service import CollectorService


def make_llm_router(service: CollectorService) -> APIRouter:
    llm_router = APIRouter()

    @llm_router.get("/llm", response_model=list[LLMSummaryItem])
    async def list_llm_summaries() -> list[LLMSummaryItem]:
        """List all LLM models seen, with aggregate stats."""
        summaries = await service.storage.list_llm_summaries()
        return [
            LLMSummaryItem(
                model=s.model,
                call_count=s.call_count,
                avg_latency_ms=s.avg_latency_ms,
                avg_token_input=s.avg_token_input,
                avg_token_output=s.avg_token_output,
                avg_context_utilisation=s.avg_context_utilisation,
            )
            for s in summaries
        ]

    @llm_router.get("/llm/trace/{trace_id}", response_model=list[LLMDetailItem])
    async def get_llm_calls_for_trace(trace_id: str) -> list[dict[str, Any]]:
        """Return all LLM calls for a given trace_id, ordered by timestamp."""
        results = await service.storage.query_llm_calls(
            LLMQueryFilters(trace_id=trace_id, limit=500)
        )
        if not results:
            raise HTTPException(
                status_code=404,
                detail=f"No LLM calls found for trace {trace_id!r}",
            )
        return results

    return llm_router
