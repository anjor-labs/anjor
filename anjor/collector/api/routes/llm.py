"""GET /llm, GET /llm/trace/{trace_id} — LLM call query endpoints (Phase 2)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException

from anjor.collector.api.schemas import DailyUsageItem, LLMDetailItem, LLMSummaryItem
from anjor.collector.storage.base import LLMQueryFilters

if TYPE_CHECKING:
    from anjor.collector.service import CollectorService


def make_llm_router(service: CollectorService) -> APIRouter:
    llm_router = APIRouter()

    @llm_router.get("/llm", response_model=list[LLMSummaryItem])
    async def list_llm_summaries(
        days: int | None = None,
        project: str | None = None,
        since_minutes: int | None = None,
    ) -> list[LLMSummaryItem]:
        """List all LLM models seen, with aggregate stats. Pass days or since_minutes to filter."""
        summaries = await service.storage.list_llm_summaries(
            days=days, project=project, since_minutes=since_minutes
        )
        return [
            LLMSummaryItem(
                model=s.model,
                call_count=s.call_count,
                avg_latency_ms=s.avg_latency_ms,
                avg_token_input=s.avg_token_input,
                avg_token_output=s.avg_token_output,
                avg_context_utilisation=s.avg_context_utilisation,
                total_token_input=s.total_token_input,
                total_token_output=s.total_token_output,
                total_cache_read=s.total_cache_read,
                total_cache_write=s.total_cache_write,
                source=s.source,
            )
            for s in summaries
        ]

    @llm_router.get("/llm/usage/daily", response_model=list[DailyUsageItem])
    async def get_daily_usage(days: int = 14, project: str | None = None) -> list[DailyUsageItem]:
        """Return token usage grouped by date and model for the last N days."""
        rows = await service.storage.list_daily_usage(days=days, project=project)
        return [DailyUsageItem(**row) for row in rows]

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

    @llm_router.get("/llm/sources")
    async def get_llm_sources() -> dict[str, list[str]]:
        sources = await service.storage.query_llm_sources()
        return {"sources": sources}

    return llm_router
