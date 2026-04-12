"""FastAPI app factory for the AgentScope collector."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentscope.collector.api.routes.calls import make_calls_router
from agentscope.collector.api.routes.events import make_events_router
from agentscope.collector.api.routes.health import make_health_router
from agentscope.collector.api.routes.intelligence import make_intelligence_router
from agentscope.collector.api.routes.llm import make_llm_router
from agentscope.collector.api.routes.tools import make_tools_router
from agentscope.collector.service import CollectorService
from agentscope.core.config import AgentScopeConfig


def create_app(
    config: AgentScopeConfig | None = None,
    service: CollectorService | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: Optional config override. Defaults to AgentScopeConfig().
        service: Optional pre-built CollectorService (useful for testing).
    """
    resolved_config = config or AgentScopeConfig()
    resolved_service = service or CollectorService(config=resolved_config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await resolved_service.start()
        yield
        await resolved_service.stop()

    app = FastAPI(
        title="AgentScope Collector",
        version="0.2.0",
        description="Local event ingestion and query API for AgentScope.",
        lifespan=lifespan,
    )

    # CORS: allow the local dashboard (default :7844) to query the collector.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:7844", "http://localhost:3000"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(make_health_router(resolved_service))
    app.include_router(make_events_router(resolved_service))
    app.include_router(make_tools_router(resolved_service))
    app.include_router(make_llm_router(resolved_service))
    app.include_router(make_calls_router(resolved_service))
    app.include_router(make_intelligence_router(resolved_service))

    return app
