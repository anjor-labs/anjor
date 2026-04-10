"""POST /events — event ingestion endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request

from agentscope.collector.api.schemas import EventIngestRequest, EventIngestResponse

if TYPE_CHECKING:
    from agentscope.collector.service import CollectorService

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

    return events_router
