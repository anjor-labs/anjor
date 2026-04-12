"""GET /health — service health check."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fastapi import APIRouter

from anjor.collector.api.schemas import HealthResponse

if TYPE_CHECKING:
    from anjor.collector.service import CollectorService

router = APIRouter()
_start_time = time.monotonic()


def make_health_router(service: CollectorService) -> APIRouter:
    health_router = APIRouter()

    @health_router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            uptime_seconds=time.monotonic() - _start_time,
            queue_depth=service.pipeline.stats.enqueued - service.pipeline.stats.dispatched,
            db_path=service.config.db_path,
        )

    return health_router
