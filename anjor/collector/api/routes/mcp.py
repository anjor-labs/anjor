"""GET /mcp — MCP server and tool analytics."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter

from anjor.collector.api.schemas import MCPResponse, MCPServerItem, MCPToolItem

if TYPE_CHECKING:
    from anjor.collector.service import CollectorService


def make_mcp_router(service: CollectorService) -> APIRouter:
    mcp_router = APIRouter()

    @mcp_router.get("/mcp", response_model=MCPResponse)
    async def get_mcp_summary(days: int | None = None) -> MCPResponse:
        """Return aggregated MCP server and tool stats, optionally filtered to last N days."""
        servers_raw, tools_raw = await asyncio.gather(
            service.storage.list_mcp_server_summaries(days=days),
            service.storage.list_mcp_tool_summaries(days=days),
        )

        servers = [
            MCPServerItem(
                server_name=s.server_name,
                tool_count=s.tool_count,
                call_count=s.call_count,
                success_count=s.success_count,
                success_rate=s.success_rate,
                avg_latency_ms=s.avg_latency_ms,
            )
            for s in servers_raw
        ]

        tools = [
            MCPToolItem(
                tool_name=t.tool_name,
                server_name=t.server_name,
                short_name=t.short_name,
                call_count=t.call_count,
                success_count=t.success_count,
                success_rate=t.success_rate,
                avg_latency_ms=t.avg_latency_ms,
            )
            for t in tools_raw
        ]

        return MCPResponse(servers=servers, tools=tools)

    return mcp_router
