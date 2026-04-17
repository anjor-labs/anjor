"""Session replay, archive, delete, and project-tagging endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from anjor.collector.api.schemas import (
    ReplayResponse,
    ReplayTurn,
    SessionItem,
    SetProjectRequest,
)
from anjor.collector.storage.sqlite import SQLiteBackend

if TYPE_CHECKING:
    from anjor.collector.service import CollectorService


def make_sessions_router(service: CollectorService) -> APIRouter:
    router = APIRouter()

    def _sqlite() -> SQLiteBackend:
        if not isinstance(service.storage, SQLiteBackend):
            raise HTTPException(status_code=503, detail="Requires SQLite backend.")
        return service.storage

    @router.get("/sessions", response_model=list[SessionItem])
    async def list_sessions(
        limit: int = 50, offset: int = 0, archived: bool = False
    ) -> list[SessionItem]:
        if not isinstance(service.storage, SQLiteBackend):
            return []
        rows = await service.storage.list_sessions(limit=limit, offset=offset, archived=archived)
        return [SessionItem(**r) for r in rows]  # type: ignore

    @router.get("/sessions/{session_id}/replay", response_model=ReplayResponse)
    async def get_replay(session_id: str) -> ReplayResponse:
        storage = _sqlite()
        turns = await storage.get_session_replay(session_id)
        if not turns:
            raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found.")
        return ReplayResponse(
            session_id=session_id,
            turn_count=len(turns),
            turns=[ReplayTurn(**t) for t in turns],  # type: ignore
        )

    @router.post("/sessions/{session_id}/archive", response_model=SessionItem)
    async def archive_session(session_id: str) -> SessionItem:
        storage = _sqlite()
        await storage.archive_session(session_id, archived=True)
        rows = await storage.list_sessions(limit=1, offset=0, archived=True)
        match = next((r for r in rows if r["session_id"] == session_id), None)
        if match is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found.")
        return SessionItem(**match)  # type: ignore

    @router.post("/sessions/{session_id}/unarchive", response_model=SessionItem)
    async def unarchive_session(session_id: str) -> SessionItem:
        storage = _sqlite()
        await storage.archive_session(session_id, archived=False)
        rows = await storage.list_sessions(limit=200, offset=0, archived=False)
        match = next((r for r in rows if r["session_id"] == session_id), None)
        if match is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found.")
        return SessionItem(**match)  # type: ignore

    @router.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str) -> None:
        storage = _sqlite()
        await storage.delete_session(session_id)

    @router.patch("/sessions/{session_id}/project", response_model=SessionItem)
    async def set_project(session_id: str, body: SetProjectRequest) -> SessionItem:
        storage = _sqlite()
        await storage.set_session_project(session_id, body.project.strip())
        # Fetch updated session from active or archived list
        for archived in (False, True):
            rows = await storage.list_sessions(limit=200, offset=0, archived=archived)
            match = next((r for r in rows if r["session_id"] == session_id), None)
            if match is not None:
                return SessionItem(**match)  # type: ignore
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found.")

    @router.get("/sessions/{session_id}/summary")
    async def get_session_summary(session_id: str) -> dict:  # type: ignore[type-arg]
        storage = _sqlite()
        row = await storage.get_session_summary(session_id)
        if row is None:
            raise HTTPException(status_code=404, detail="No summary found")
        return row

    return router
