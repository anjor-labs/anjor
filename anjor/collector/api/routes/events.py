"""POST /events — event ingestion endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request

from anjor.collector.api.schemas import EventIngestRequest, EventIngestResponse, FlushResponse

if TYPE_CHECKING:
    from anjor.collector.service import CollectorService

_MAX_PAYLOAD_BYTES_DEFAULT = 512 * 1024


def make_events_router(service: CollectorService) -> APIRouter:
    events_router = APIRouter()
    max_bytes = service.config.max_payload_size_kb * 1024

    @events_router.post("/events", response_model=EventIngestResponse, status_code=202)
    async def ingest_event(request: Request, body: EventIngestRequest) -> EventIngestResponse:
        # Validate payload size
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Payload too large. Max {service.config.max_payload_size_kb}KB.",
            )

        event_dict = body.model_dump()
        await service.storage.write_event(event_dict)
        return EventIngestResponse()

    @events_router.post("/flush", response_model=FlushResponse)
    async def flush_batch() -> FlushResponse:
        """Force-flush all pending batch writes to storage.

        Returns the count of tool_call events written in this flush.  Use this
        in development or tests immediately after posting events to make them
        queryable without waiting for the 500 ms batch interval.
        """
        flushed = await service.storage.flush()
        return FlushResponse(flushed=flushed)

    return events_router
