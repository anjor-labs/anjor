"""Unit tests for SQLiteBackend save_baseline / load_baseline."""

from __future__ import annotations

import json

import pytest

from anjor.collector.storage.sqlite import SQLiteBackend


@pytest.fixture
async def storage() -> SQLiteBackend:
    backend = SQLiteBackend(db_path=":memory:", batch_size=1, batch_interval_ms=9999)
    await backend.connect()
    yield backend
    await backend.close()


class TestBaselines:
    async def test_save_and_load_baseline(self, storage: SQLiteBackend) -> None:
        metrics = {"call_count": 10, "success_rate": 0.9}
        await storage.save_baseline("v1", "24h", json.dumps(metrics))

        row = await storage.load_baseline("v1")

        assert row is not None
        assert row["name"] == "v1"
        assert row["window"] == "24h"
        loaded = json.loads(row["metrics_json"])
        assert loaded["call_count"] == 10
        assert loaded["success_rate"] == pytest.approx(0.9)

    async def test_load_missing_returns_none(self, storage: SQLiteBackend) -> None:
        result = await storage.load_baseline("nonexistent")
        assert result is None

    async def test_save_overwrites_existing(self, storage: SQLiteBackend) -> None:
        await storage.save_baseline("baseline", "24h", json.dumps({"call_count": 5}))
        await storage.save_baseline("baseline", "7d", json.dumps({"call_count": 99}))

        row = await storage.load_baseline("baseline")

        assert row is not None
        assert row["window"] == "7d"
        loaded = json.loads(row["metrics_json"])
        assert loaded["call_count"] == 99
