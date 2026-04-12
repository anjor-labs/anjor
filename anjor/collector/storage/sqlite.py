"""SQLiteBackend — aiosqlite implementation with WAL mode and batch writes."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from anjor.collector.storage.base import (
    LLMQueryFilters,
    LLMSummary,
    QueryFilters,
    SchemaSnapshot,
    StorageBackend,
    ToolSummary,
)

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SQLiteBackend(StorageBackend):
    """SQLite storage backend using aiosqlite.

    - WAL mode for concurrent reads.
    - Batch writer flushes every batch_interval_ms OR batch_size events,
      whichever comes first.
    - In-memory mode: pass db_path=":memory:" (for tests).
    - No SQLite-specific functions are used in application queries.
    """

    def __init__(
        self,
        db_path: str = "anjor.db",
        batch_size: int = 100,
        batch_interval_ms: int = 500,
    ) -> None:
        self._db_path = db_path
        self._batch_size = batch_size
        self._batch_interval_ms = batch_interval_ms
        self._conn: aiosqlite.Connection | None = None
        self._batch: list[dict[str, Any]] = []
        self._flush_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """Open connection, apply migrations, start batch flusher."""
        self._conn = await aiosqlite.connect(self._db_path)
        # DECISION: row_factory=aiosqlite.Row so rows behave like dicts — callers
        # can access columns by name without knowing the column index.
        self._conn.row_factory = aiosqlite.Row
        # DECISION: WAL mode for concurrent reads — the API reads while the batch writer
        # writes; WAL avoids full table locks that would stall dashboard queries.
        if self._db_path != ":memory:":
            await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._run_migrations()
        self._flush_task = asyncio.create_task(self._periodic_flush())

    async def _run_migrations(self) -> None:
        """Apply SQL migration files in version order."""
        assert self._conn is not None
        await self._conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                version    INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )"""
        )
        await self._conn.commit()

        migration_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
        for path in migration_files:
            version = int(path.stem.split("_")[0])
            cursor = await self._conn.execute(
                "SELECT version FROM schema_migrations WHERE version = ?",
                (version,),
            )
            if await cursor.fetchone() is not None:
                continue  # already applied
            sql = path.read_text()
            await self._conn.executescript(sql)
            await self._conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, _now_iso()),
            )
            await self._conn.commit()

    # ------------------------------------------------------------------
    # Batch write machinery
    # ------------------------------------------------------------------

    async def _periodic_flush(self) -> None:
        # DECISION: time-based flush as a safety net so events are written even when
        # traffic is low and the batch_size threshold is never reached.
        interval = self._batch_interval_ms / 1000.0
        while True:
            await asyncio.sleep(interval)
            await self._flush()

    async def _flush(self) -> None:
        async with self._lock:
            if not self._batch:
                return
            batch = self._batch[:]
            self._batch.clear()

        assert self._conn is not None
        await self._conn.executemany(
            """INSERT INTO tool_calls (
                event_type, trace_id, session_id, agent_id, timestamp, sequence_no,
                tool_name, status, failure_type, latency_ms,
                input_payload, output_payload, input_schema_hash, output_schema_hash,
                token_usage_input, token_usage_output,
                drift_detected, drift_missing, drift_unexpected, drift_expected_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [self._row_from_event(e) for e in batch],
        )
        await self._conn.commit()

    @staticmethod
    def _row_from_event(event: dict[str, Any]) -> tuple[Any, ...]:
        drift = event.get("schema_drift") or {}
        usage = event.get("token_usage") or {}
        return (
            event.get("event_type", "tool_call"),
            event.get("trace_id", ""),
            event.get("session_id", ""),
            event.get("agent_id", "default"),
            event.get("timestamp", _now_iso()),
            event.get("sequence_no", 0),
            event.get("tool_name", ""),
            event.get("status", ""),
            event.get("failure_type"),
            event.get("latency_ms", 0.0),
            json.dumps(event.get("input_payload", {})),
            json.dumps(event.get("output_payload", {})),
            event.get("input_schema_hash", ""),
            event.get("output_schema_hash", ""),
            usage.get("input"),
            usage.get("output"),
            1 if drift.get("detected") else 0 if drift else None,
            json.dumps(drift.get("missing_fields", [])) if drift else None,
            json.dumps(drift.get("unexpected_fields", [])) if drift else None,
            drift.get("expected_hash"),
        )

    # ------------------------------------------------------------------
    # StorageBackend interface
    # ------------------------------------------------------------------

    async def write_event(self, event_data: dict[str, Any]) -> None:
        """Route and persist a single event by event_type."""
        event_type = event_data.get("event_type")
        if event_type == "tool_call":
            async with self._lock:
                self._batch.append(event_data)
                should_flush = len(self._batch) >= self._batch_size
            if should_flush:
                await self._flush()
        elif event_type == "llm_call":
            await self.write_llm_event(event_data)

    async def write_llm_event(self, event_data: dict[str, Any]) -> None:
        """Persist an LLMCallEvent directly to the llm_calls table (not batched)."""
        assert self._conn is not None
        usage = event_data.get("token_usage") or {}
        await self._conn.execute(
            """INSERT INTO llm_calls (
                trace_id, session_id, agent_id, timestamp, sequence_no,
                model, latency_ms,
                token_input, token_output, token_cache_read,
                context_window_used, context_window_limit, context_utilisation,
                prompt_hash, system_prompt_hash, messages_count, finish_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_data.get("trace_id", ""),
                event_data.get("session_id", ""),
                event_data.get("agent_id", "default"),
                event_data.get("timestamp", _now_iso()),
                event_data.get("sequence_no", 0),
                event_data.get("model", ""),
                event_data.get("latency_ms", 0.0),
                usage.get("input"),
                usage.get("output"),
                usage.get("cache_read"),
                event_data.get("context_window_used"),
                event_data.get("context_window_limit"),
                event_data.get("context_utilisation"),
                event_data.get("prompt_hash"),
                event_data.get("system_prompt_hash"),
                event_data.get("messages_count"),
                event_data.get("finish_reason"),
            ),
        )
        await self._conn.commit()

    async def query_tool_calls(self, filters: QueryFilters) -> list[dict[str, Any]]:
        """Query tool calls with optional filters. Parameterised SQL only."""
        assert self._conn is not None
        conditions: list[str] = []
        params: list[Any] = []

        if filters.tool_name:
            conditions.append("tool_name = ?")
            params.append(filters.tool_name)
        if filters.status:
            conditions.append("status = ?")
            params.append(filters.status)
        if filters.since:
            conditions.append("timestamp >= ?")
            params.append(filters.since.isoformat())
        if filters.until:
            conditions.append("timestamp <= ?")
            params.append(filters.until.isoformat())

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.extend([filters.limit, filters.offset])

        cursor = await self._conn.execute(
            f"SELECT * FROM tool_calls {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",  # noqa: S608
            params,
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_tool_summary(self, tool_name: str) -> ToolSummary | None:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT status, latency_ms FROM tool_calls WHERE tool_name = ?",
            (tool_name,),
        )
        rows = await cursor.fetchall()
        if not rows:
            return None
        return self._compute_summary(tool_name, list(rows))

    async def list_tool_summaries(self) -> list[ToolSummary]:
        assert self._conn is not None
        cursor = await self._conn.execute("SELECT DISTINCT tool_name FROM tool_calls")
        names = [row[0] for row in await cursor.fetchall()]
        summaries = []
        for name in names:
            summary = await self.get_tool_summary(name)
            if summary:
                summaries.append(summary)
        return summaries

    @staticmethod
    def _compute_summary(tool_name: str, rows: list[aiosqlite.Row]) -> ToolSummary:
        latencies = sorted(row["latency_ms"] for row in rows)
        success_count = sum(1 for row in rows if row["status"] == "success")
        call_count = len(rows)
        avg = sum(latencies) / call_count if latencies else 0.0

        def percentile(data: list[float], p: float) -> float:
            if not data:
                return 0.0
            idx = int(len(data) * p / 100)
            return data[min(idx, len(data) - 1)]

        return ToolSummary(
            tool_name=tool_name,
            call_count=call_count,
            success_count=success_count,
            failure_count=call_count - success_count,
            avg_latency_ms=avg,
            p50_latency_ms=percentile(latencies, 50),
            p95_latency_ms=percentile(latencies, 95),
            p99_latency_ms=percentile(latencies, 99),
        )

    async def query_llm_calls(self, filters: LLMQueryFilters) -> list[dict[str, Any]]:
        """Query LLM call events with optional filters."""
        assert self._conn is not None
        conditions: list[str] = []
        params: list[Any] = []

        if filters.trace_id:
            conditions.append("trace_id = ?")
            params.append(filters.trace_id)
        if filters.agent_id:
            conditions.append("agent_id = ?")
            params.append(filters.agent_id)
        if filters.model:
            conditions.append("model = ?")
            params.append(filters.model)
        if filters.since:
            conditions.append("timestamp >= ?")
            params.append(filters.since.isoformat())
        if filters.until:
            conditions.append("timestamp <= ?")
            params.append(filters.until.isoformat())

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.extend([filters.limit, filters.offset])

        cursor = await self._conn.execute(
            f"SELECT * FROM llm_calls {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",  # noqa: S608
            params,
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def list_llm_summaries(self) -> list[LLMSummary]:
        """Return aggregated stats per model from llm_calls table."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            """SELECT
                model,
                count(*) as call_count,
                avg(latency_ms) as avg_latency_ms,
                avg(token_input) as avg_token_input,
                avg(token_output) as avg_token_output,
                avg(context_utilisation) as avg_context_utilisation
               FROM llm_calls
               GROUP BY model"""
        )
        rows = await cursor.fetchall()
        return [
            LLMSummary(
                model=row["model"],
                call_count=row["call_count"],
                avg_latency_ms=row["avg_latency_ms"] or 0.0,
                avg_token_input=row["avg_token_input"] or 0.0,
                avg_token_output=row["avg_token_output"] or 0.0,
                avg_context_utilisation=row["avg_context_utilisation"] or 0.0,
            )
            for row in rows
        ]

    async def write_schema_snapshot(self, snap: SchemaSnapshot) -> None:
        assert self._conn is not None
        await self._conn.execute(
            """INSERT INTO schema_snapshots
               (tool_name, payload_type, schema_hash, captured_at, sample_payload)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(tool_name, payload_type)
               DO UPDATE SET schema_hash=excluded.schema_hash,
                             captured_at=excluded.captured_at,
                             sample_payload=excluded.sample_payload""",
            (
                snap.tool_name,
                snap.payload_type,
                snap.schema_hash,
                snap.captured_at.isoformat(),
                json.dumps(snap.sample_payload),
            ),
        )
        await self._conn.commit()

    async def get_schema_snapshot(self, tool_name: str, payload_type: str) -> SchemaSnapshot | None:
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT * FROM schema_snapshots WHERE tool_name = ? AND payload_type = ?",
            (tool_name, payload_type),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return SchemaSnapshot(
            tool_name=row["tool_name"],
            payload_type=row["payload_type"],
            schema_hash=row["schema_hash"],
            captured_at=datetime.fromisoformat(row["captured_at"]),
            sample_payload=json.loads(row["sample_payload"]),
        )

    async def query_tool_calls_for_analysis(
        self, tool_name: str | None = None, limit: int = 2000
    ) -> list[dict[str, Any]]:
        """Return raw tool call rows for intelligence analysis.

        Returns all columns (including drift_detected) so analysers can
        compute reliability and schema stability scores.
        """
        assert self._conn is not None
        if tool_name:
            cursor = await self._conn.execute(
                "SELECT * FROM tool_calls WHERE tool_name = ? ORDER BY timestamp DESC LIMIT ?",
                (tool_name, limit),
            )
        else:
            cursor = await self._conn.execute(
                "SELECT * FROM tool_calls ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def query_drift_summary(self) -> list[dict[str, Any]]:
        """Return per-tool drift counts from tool_calls table."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            """SELECT
                tool_name,
                count(*) AS total_calls,
                sum(CASE WHEN drift_detected = 1 THEN 1 ELSE 0 END) AS drift_calls
               FROM tool_calls
               GROUP BY tool_name"""
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def close(self) -> None:
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush()  # flush remaining
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
