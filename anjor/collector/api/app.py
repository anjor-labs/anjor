"""FastAPI app factory for the Anjor collector."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from anjor.collector.api.routes.calls import make_calls_router
from anjor.collector.api.routes.events import make_events_router
from anjor.collector.api.routes.health import make_health_router
from anjor.collector.api.routes.intelligence import make_intelligence_router
from anjor.collector.api.routes.llm import make_llm_router
from anjor.collector.api.routes.tools import make_tools_router
from anjor.collector.api.routes.traces import make_traces_router
from anjor.collector.service import CollectorService
from anjor.core.config import AnjorConfig

_STATIC_DIR = Path(__file__).parent.parent.parent / "dashboard" / "static"


def create_app(
    config: AnjorConfig | None = None,
    service: CollectorService | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: Optional config override. Defaults to AnjorConfig().
        service: Optional pre-built CollectorService (useful for testing).
    """
    resolved_config = config or AnjorConfig()
    resolved_service = service or CollectorService(config=resolved_config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await resolved_service.start()
        yield
        await resolved_service.stop()

    app = FastAPI(
        title="Anjor Collector",
        version="0.4.0",
        description="Local event ingestion and query API for Anjor.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(make_health_router(resolved_service))
    app.include_router(make_events_router(resolved_service))
    app.include_router(make_tools_router(resolved_service))
    app.include_router(make_llm_router(resolved_service))
    app.include_router(make_calls_router(resolved_service))
    app.include_router(make_intelligence_router(resolved_service))
    app.include_router(make_traces_router(resolved_service))

    @app.get("/", include_in_schema=False)
    async def root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/ui/index.html")

    if _STATIC_DIR.exists():
        app.mount("/ui", StaticFiles(directory=str(_STATIC_DIR), html=True), name="ui")

    return app
