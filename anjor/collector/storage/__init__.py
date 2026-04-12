"""Storage package — backend factory and ABC re-export."""

from __future__ import annotations

from typing import TYPE_CHECKING

from anjor.collector.storage.base import StorageBackend

if TYPE_CHECKING:
    from anjor.core.config import AnjorConfig


def create_storage_backend(config: AnjorConfig) -> StorageBackend:
    """Instantiate the configured storage backend.

    Currently only sqlite is implemented. postgres and clickhouse will be
    added in future releases — the config fields are accepted now so that
    user configuration written today will not need to change.
    """
    if config.storage_backend == "sqlite":
        from anjor.collector.storage.sqlite import SQLiteBackend

        return SQLiteBackend(
            db_path=config.db_path,
            batch_size=config.batch_size,
            batch_interval_ms=config.batch_interval_ms,
        )

    raise NotImplementedError(
        f"storage_backend={config.storage_backend!r} is not yet implemented. "
        "Only 'sqlite' is available in this release."
    )


__all__ = ["StorageBackend", "create_storage_backend"]
