"""GET /tools, GET /tools/{name} — tool query endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from anjor.collector.api.schemas import ToolDetailResponse, ToolListItem

if TYPE_CHECKING:
    from anjor.collector.service import CollectorService


def make_tools_router(service: CollectorService) -> APIRouter:
    tools_router = APIRouter()

    @tools_router.get("/tools", response_model=list[ToolListItem])
    async def list_tools() -> list[ToolListItem]:
        summaries = await service.storage.list_tool_summaries()
        return [
            ToolListItem(
                tool_name=s.tool_name,
                call_count=s.call_count,
                success_rate=s.success_rate,
                avg_latency_ms=s.avg_latency_ms,
            )
            for s in summaries
        ]

    @tools_router.get("/tools/{tool_name}", response_model=ToolDetailResponse)
    async def get_tool(tool_name: str) -> ToolDetailResponse:
        summary = await service.storage.get_tool_summary(tool_name)
        if summary is None:
            raise HTTPException(status_code=404, detail=f"Tool {tool_name!r} not found")
        return ToolDetailResponse(
            tool_name=summary.tool_name,
            call_count=summary.call_count,
            success_count=summary.success_count,
            failure_count=summary.failure_count,
            success_rate=summary.success_rate,
            avg_latency_ms=summary.avg_latency_ms,
            p50_latency_ms=summary.p50_latency_ms,
            p95_latency_ms=summary.p95_latency_ms,
            p99_latency_ms=summary.p99_latency_ms,
        )

    return tools_router
