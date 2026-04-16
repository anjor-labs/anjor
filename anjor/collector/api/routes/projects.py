"""GET /projects — per-project aggregated stats."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from anjor.collector.api.schemas import ProjectSummaryItem

if TYPE_CHECKING:
    from anjor.collector.service import CollectorService


def make_projects_router(service: CollectorService) -> APIRouter:
    projects_router = APIRouter()

    @projects_router.get("/projects", response_model=list[ProjectSummaryItem])
    async def list_projects() -> list[ProjectSummaryItem]:
        """Return per-project aggregated stats.

        Projects are auto-detected from transcript file paths or set explicitly
        via --project. Only projects with at least one tagged event are returned.
        """
        summaries = await service.storage.list_projects()
        return [
            ProjectSummaryItem(
                project=s.project,
                tool_call_count=s.tool_call_count,
                llm_call_count=s.llm_call_count,
                total_token_input=s.total_token_input,
                total_token_output=s.total_token_output,
                first_seen=s.first_seen,
                last_seen=s.last_seen,
            )
            for s in summaries
        ]

    return projects_router
