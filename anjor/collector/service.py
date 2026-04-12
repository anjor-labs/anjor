"""CollectorService — orchestrates storage, pipeline, and API."""

from __future__ import annotations

from anjor.collector.storage import StorageBackend, create_storage_backend
from anjor.core.config import AnjorConfig
from anjor.core.pipeline.pipeline import EventPipeline


class CollectorService:
    """Wires together storage, pipeline, and the REST API."""

    def __init__(
        self,
        config: AnjorConfig | None = None,
        storage: StorageBackend | None = None,
        pipeline: EventPipeline | None = None,
    ) -> None:
        self.config = config or AnjorConfig()
        self.storage = storage or create_storage_backend(self.config)
        self.pipeline = pipeline or EventPipeline()

    async def start(self) -> None:
        """Connect storage and start the event pipeline."""
        await self.storage.connect()
        await self.pipeline.start()

    async def stop(self) -> None:
        """Drain pipeline, flush storage, close connection."""
        await self.pipeline.stop()
        await self.storage.close()
