"""CollectorService — orchestrates storage, pipeline, and API."""

from __future__ import annotations

from agentscope.collector.storage.sqlite import SQLiteBackend
from agentscope.core.config import AgentScopeConfig
from agentscope.core.pipeline.pipeline import EventPipeline


class CollectorService:
    """Wires together storage, pipeline, and the REST API."""

    def __init__(
        self,
        config: AgentScopeConfig | None = None,
        storage: SQLiteBackend | None = None,
        pipeline: EventPipeline | None = None,
    ) -> None:
        self.config = config or AgentScopeConfig()
        self.storage = storage or SQLiteBackend(
            db_path=self.config.db_path,
            batch_size=self.config.batch_size,
            batch_interval_ms=self.config.batch_interval_ms,
        )
        self.pipeline = pipeline or EventPipeline()

    async def start(self) -> None:
        """Connect storage and start the event pipeline."""
        await self.storage.connect()
        await self.pipeline.start()

    async def stop(self) -> None:
        """Drain pipeline, flush storage, close connection."""
        await self.pipeline.stop()
        await self.storage.close()
