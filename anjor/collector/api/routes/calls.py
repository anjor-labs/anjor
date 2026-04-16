"""GET /calls — tool call event query endpoint (used by dashboard call inspector)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Query

from anjor.collector.storage.base import QueryFilters

if TYPE_CHECKING:
    from anjor.collector.service import CollectorService


def make_calls_router(service: CollectorService) -> APIRouter:
    calls_router = APIRouter()

    @calls_router.get("/calls")
    async def list_calls(
        tool_name: str | None = Query(default=None),
        project: str | None = Query(default=None),
        drift_only: bool = Query(default=False),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> list[dict[str, Any]]:
        """Return recent tool call events with optional filters.

        - drift_only=true returns only calls where schema drift was detected.
        - Ordered by timestamp DESC.
        """
        filters = QueryFilters(tool_name=tool_name, project=project, limit=limit, offset=offset)
        calls = await service.storage.query_tool_calls(filters)
        if drift_only:
            calls = [c for c in calls if c.get("drift_detected")]
        return calls

    return calls_router
