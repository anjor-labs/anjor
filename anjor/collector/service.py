"""CollectorService — orchestrates storage, pipeline, and API."""

from __future__ import annotations

from typing import Any

from anjor.collector.export.otlp import OtlpExportHandler
from anjor.collector.storage import StorageBackend, create_storage_backend
from anjor.core.config import AnjorConfig
from anjor.core.pipeline.handlers import AlertHandler
from anjor.core.pipeline.pipeline import EventPipeline


class CollectorService:
    """Wires together storage, pipeline, and the REST API."""

    def __init__(
        self,
        config: AnjorConfig | None = None,
        storage: StorageBackend | None = None,
        pipeline: EventPipeline | None = None,
        alert_handler: AlertHandler | None = None,
    ) -> None:
        self.config = config or AnjorConfig()
        self.storage = storage or create_storage_backend(self.config)
        self.pipeline = pipeline or EventPipeline()
        self.alert_handler = alert_handler or AlertHandler(self.config.alerts)
        self._otlp_handler: OtlpExportHandler | None = None

    async def start(self) -> None:
        """Connect storage and start the event pipeline."""
        await self.storage.connect()
        if self.config.export.otlp_endpoint:
            self._otlp_handler = OtlpExportHandler(
                endpoint=self.config.export.otlp_endpoint,
                headers=self.config.export.otlp_headers,
            )
            self.pipeline.add_handler(self._otlp_handler)
        await self.pipeline.start()

    async def stop(self) -> None:
        """Drain pipeline, flush storage, close connection."""
        await self.pipeline.stop()
        if self._otlp_handler is not None:
            await self._otlp_handler.shutdown()
        await self.storage.close()

    async def ingest(self, event_data: dict[str, Any]) -> None:
        """Write event to storage and evaluate alert conditions."""
        await self.storage.write_event(event_data)
        await self.alert_handler.handle_dict(event_data)
