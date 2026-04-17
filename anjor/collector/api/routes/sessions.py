"""GET /sessions and GET /sessions/{session_id}/replay — conversation replay endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from anjor.collector.api.schemas import ReplayResponse, ReplayTurn, SessionItem
from anjor.collector.storage.sqlite import SQLiteBackend

if TYPE_CHECKING:
    from anjor.collector.service import CollectorService


def make_sessions_router(service: CollectorService) -> APIRouter:
    router = APIRouter()

    @router.get("/sessions", response_model=list[SessionItem])
    async def list_sessions(limit: int = 50, offset: int = 0) -> list[SessionItem]:
        """List sessions that have captured messages, newest first."""
        if not isinstance(service.storage, SQLiteBackend):
            return []
        rows = await service.storage.list_sessions(limit=limit, offset=offset)
        return [SessionItem(**r) for r in rows]  # type: ignore

    @router.get("/sessions/{session_id}/replay", response_model=ReplayResponse)
    async def get_replay(session_id: str) -> ReplayResponse:
        """Return all turns (messages + tool calls) for a session in timestamp order."""
        if not isinstance(service.storage, SQLiteBackend):
            raise HTTPException(status_code=503, detail="Replay requires SQLite backend.")
        turns = await service.storage.get_session_replay(session_id)
        if not turns:
            raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found.")
        return ReplayResponse(
            session_id=session_id,
            turn_count=len(turns),
            turns=[ReplayTurn(**t) for t in turns],  # type: ignore
        )

    return router
