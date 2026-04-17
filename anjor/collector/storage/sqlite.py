"""SQLiteBackend — aiosqlite implementation with WAL mode and batch writes."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from anjor.collector.storage.base import (
    LLMQueryFilters,
    LLMSummary,
    MCPServerSummary,
    MCPToolSummary,
    ProjectSummary,
    QueryFilters,
    SchemaSnapshot,
    StorageBackend,
    ToolSummary,
    TraceSummary,
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
        await self._ensure_columns()
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
            # DECISION: execute statements individually rather than executescript()
            # because executescript() issues an implicit COMMIT before running, which
            # interferes with ALTER TABLE on Python 3.11.
            statements = [
                s.strip() for s in re.split(r";", re.sub(r"--[^\n]*", "", sql)) if s.strip()
            ]
            for stmt in statements:
                upper = stmt.upper().lstrip()
                # For ALTER TABLE ADD COLUMN: check if the column already exists so
                # migration 005 is idempotent on databases created from the updated
                # 001/002 schemas (which include the column from the start).
                if upper.startswith("ALTER TABLE") and "ADD COLUMN" in upper:
                    m = re.match(
                        r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)",
                        stmt.strip(),
                        re.IGNORECASE,
                    )
                    if m:
                        tbl, col = m.group(1), m.group(2).lower()
                        pi = await self._conn.execute(f"PRAGMA table_info({tbl})")  # noqa: S608
                        existing = {row[1].lower() for row in await pi.fetchall()}
                        if col in existing:
                            continue  # already present — skip
                    # Commit any open implicit transaction before DDL so the ALTER
                    # takes effect reliably on Python 3.11 (isolation_level='').
                    await self._conn.commit()
                await self._conn.execute(stmt)
            await self._conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, _now_iso()),
            )
            await self._conn.commit()

    async def _ensure_columns(self) -> None:
        """Belt-and-suspenders: verify critical columns exist and add any that are missing.

        Guards against Python 3.12+ DDL transaction-handling differences that can
        cause ALTER TABLE statements inside _run_migrations to silently roll back on
        existing databases (e.g. a DB created with an older release of anjor).
        """
        assert self._conn is not None
        needed: list[tuple[str, str, str]] = [
            ("tool_calls", "source", "TEXT NOT NULL DEFAULT ''"),
            ("llm_calls", "source", "TEXT NOT NULL DEFAULT ''"),
            ("tool_calls", "project", "TEXT NOT NULL DEFAULT ''"),
            ("llm_calls", "project", "TEXT NOT NULL DEFAULT ''"),
        ]
        altered = False
        for table, col, typedef in needed:
            cur = await self._conn.execute(f"PRAGMA table_info({table})")  # noqa: S608
            existing = {row[1].lower() for row in await cur.fetchall()}
            if col not in existing:
                await self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {col} {typedef}"  # noqa: S608
                )
                altered = True
        if altered:
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
            await self._flush()  # return value intentionally discarded

    async def _flush(self) -> int:
        """Drain the pending batch to SQLite. Returns the number of rows written."""
        async with self._lock:
            if not self._batch:
                return 0
            batch = self._batch[:]
            self._batch.clear()

        assert self._conn is not None
        await self._conn.executemany(
            """INSERT INTO tool_calls (
                event_type, trace_id, session_id, agent_id, timestamp, sequence_no,
                tool_name, status, failure_type, latency_ms,
                input_payload, output_payload, input_schema_hash, output_schema_hash,
                token_usage_input, token_usage_output,
                drift_detected, drift_missing, drift_unexpected, drift_expected_hash,
                source, project
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [self._row_from_event(e) for e in batch],
        )
        await self._conn.commit()
        return len(batch)

    async def flush(self) -> int:
        """Force-flush all pending batch writes immediately.

        Returns the number of tool_call events written in this flush.  LLM and
        span events are written synchronously (unbatched) so they are always
        immediately queryable — only tool_call events go through the batch writer.
        """
        return await self._flush()

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
            event.get("source", ""),
            event.get("project", ""),
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
        elif event_type == "agent_span":
            await self.write_span(event_data)
        elif event_type == "message":
            await self.write_message_event(event_data)

    async def write_message_event(self, event_data: dict[str, Any]) -> None:
        """Persist a MessageEvent to session_messages."""
        assert self._conn is not None
        await self._conn.execute(
            """INSERT INTO session_messages (
                session_id, trace_id, agent_id, timestamp, turn_index,
                role, content_preview, token_count, source, project
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_data.get("session_id", ""),
                event_data.get("trace_id", ""),
                event_data.get("agent_id", "default"),
                event_data.get("timestamp", ""),
                event_data.get("turn_index", 0),
                event_data.get("role", "user"),
                event_data.get("content_preview", ""),
                event_data.get("token_count"),
                event_data.get("source", ""),
                event_data.get("project", ""),
            ),
        )
        await self._conn.commit()

    async def write_llm_event(self, event_data: dict[str, Any]) -> None:
        """Persist an LLMCallEvent directly to the llm_calls table (not batched)."""
        assert self._conn is not None
        usage = event_data.get("token_usage") or {}
        await self._conn.execute(
            """INSERT INTO llm_calls (
                trace_id, session_id, agent_id, timestamp, sequence_no,
                model, latency_ms,
                token_input, token_output, token_cache_read, token_cache_write,
                context_window_used, context_window_limit, context_utilisation,
                prompt_hash, system_prompt_hash, messages_count, finish_reason,
                source, project
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                usage.get("cache_creation"),
                event_data.get("context_window_used"),
                event_data.get("context_window_limit"),
                event_data.get("context_utilisation"),
                event_data.get("prompt_hash"),
                event_data.get("system_prompt_hash"),
                event_data.get("messages_count"),
                event_data.get("finish_reason"),
                event_data.get("source", ""),
                event_data.get("project", ""),
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
        if filters.project:
            conditions.append("project = ?")
            params.append(filters.project)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.extend([filters.limit, filters.offset])

        cursor = await self._conn.execute(
            f"SELECT * FROM tool_calls {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",  # noqa: S608
            params,
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_tool_summary(
        self,
        tool_name: str,
        project: str | None = None,
        since_minutes: int | None = None,
    ) -> ToolSummary | None:
        assert self._conn is not None
        conditions = ["tool_name = ?"]
        params: list[object] = [tool_name]
        if project:
            conditions.append("project = ?")
            params.append(project)
        if since_minutes is not None:
            conditions.append("timestamp >= datetime('now', ?)")
            params.append(f"-{since_minutes} minutes")
        where = " AND ".join(conditions)
        cursor = await self._conn.execute(
            f"SELECT status, latency_ms FROM tool_calls WHERE {where}",  # noqa: S608
            params,
        )
        rows = await cursor.fetchall()
        if not rows:
            return None
        return self._compute_summary(tool_name, list(rows))

    async def list_tool_summaries(
        self,
        project: str | None = None,
        since_minutes: int | None = None,
    ) -> list[ToolSummary]:
        assert self._conn is not None
        conditions: list[str] = []
        params: list[object] = []
        if project:
            conditions.append("project = ?")
            params.append(project)
        if since_minutes is not None:
            conditions.append("timestamp >= datetime('now', ?)")
            params.append(f"-{since_minutes} minutes")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        cursor = await self._conn.execute(
            f"SELECT DISTINCT tool_name FROM tool_calls {where}",  # noqa: S608
            params,
        )
        names = [row[0] for row in await cursor.fetchall()]
        summaries = []
        for name in names:
            summary = await self.get_tool_summary(
                name, project=project, since_minutes=since_minutes
            )
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
        if filters.project:
            conditions.append("project = ?")
            params.append(filters.project)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.extend([filters.limit, filters.offset])

        cursor = await self._conn.execute(
            f"SELECT * FROM llm_calls {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?",  # noqa: S608
            params,
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def list_llm_summaries(
        self,
        days: int | None = None,
        project: str | None = None,
        since_minutes: int | None = None,
    ) -> list[LLMSummary]:
        """Return aggregated stats per model from llm_calls table."""
        assert self._conn is not None
        where_parts: list[str] = []
        params: list[Any] = []
        if since_minutes is not None:
            where_parts.append("timestamp >= datetime('now', ?)")
            params.append(f"-{since_minutes} minutes")
        elif days is not None:
            where_parts.append("timestamp >= datetime('now', ?)")
            params.append(f"-{days} days")
        if project:
            where_parts.append("project = ?")
            params.append(project)
        where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        cursor = await self._conn.execute(
            f"""SELECT
                model,
                count(*)                    AS call_count,
                avg(latency_ms)             AS avg_latency_ms,
                avg(token_input)            AS avg_token_input,
                avg(token_output)           AS avg_token_output,
                avg(context_utilisation)    AS avg_context_utilisation,
                sum(coalesce(token_input,  0)) AS total_token_input,
                sum(coalesce(token_output, 0)) AS total_token_output,
                sum(coalesce(token_cache_read,  0)) AS total_cache_read,
                sum(coalesce(token_cache_write, 0)) AS total_cache_write,
                max(source)                 AS source
               FROM llm_calls
               {where}
               GROUP BY model""",  # noqa: S608
            params,
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
                total_token_input=row["total_token_input"] or 0,
                total_token_output=row["total_token_output"] or 0,
                total_cache_read=row["total_cache_read"] or 0,
                total_cache_write=row["total_cache_write"] or 0,
                source=row["source"] or "",
            )
            for row in rows
        ]

    async def list_daily_usage(self, days: int = 14) -> list[dict[str, Any]]:
        """Return token usage grouped by date and model for the last N days."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            """SELECT
                substr(timestamp, 1, 10)       AS date,
                model,
                sum(coalesce(token_input,  0)) AS tokens_in,
                sum(coalesce(token_output, 0)) AS tokens_out,
                sum(coalesce(token_cache_read,  0)) AS cache_read,
                sum(coalesce(token_cache_write, 0)) AS cache_write,
                count(*)                       AS calls
               FROM llm_calls
               WHERE timestamp >= datetime('now', ?)
               GROUP BY date, model
               ORDER BY date ASC""",
            (f"-{days} days",),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def query_llm_sources(self) -> list[str]:
        import sqlite3 as _sqlite3

        assert self._conn is not None
        try:
            cursor = await self._conn.execute(
                "SELECT DISTINCT source FROM llm_calls WHERE source != ''"
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]
        except _sqlite3.OperationalError:
            return []

    async def list_projects(self) -> list[ProjectSummary]:
        """Return per-project aggregated stats from tool_calls and llm_calls."""
        assert self._conn is not None
        tc_cursor = await self._conn.execute(
            """SELECT project,
                      count(*)        AS tool_call_count,
                      min(timestamp)  AS first_seen,
                      max(timestamp)  AS last_seen
               FROM tool_calls
               WHERE project != ''
               GROUP BY project"""
        )
        tc_rows = {row["project"]: dict(row) for row in await tc_cursor.fetchall()}

        llm_cursor = await self._conn.execute(
            """SELECT project,
                      count(*)                            AS llm_call_count,
                      sum(coalesce(token_input,  0))      AS total_token_input,
                      sum(coalesce(token_output, 0))      AS total_token_output
               FROM llm_calls
               WHERE project != ''
               GROUP BY project"""
        )
        llm_rows = {row["project"]: dict(row) for row in await llm_cursor.fetchall()}

        all_projects = sorted(set(tc_rows) | set(llm_rows))
        result = []
        for proj in all_projects:
            tc = tc_rows.get(proj, {})
            llm = llm_rows.get(proj, {})
            result.append(
                ProjectSummary(
                    project=proj,
                    tool_call_count=tc.get("tool_call_count", 0),
                    llm_call_count=llm.get("llm_call_count", 0),
                    total_token_input=llm.get("total_token_input", 0),
                    total_token_output=llm.get("total_token_output", 0),
                    first_seen=tc.get("first_seen") or "",
                    last_seen=tc.get("last_seen") or "",
                )
            )
        result.sort(key=lambda p: p.last_seen, reverse=True)
        return result

    async def list_mcp_server_summaries(self, days: int | None = None) -> list[MCPServerSummary]:
        """Return per-server stats for all tools whose name starts with mcp__."""
        assert self._conn is not None
        # GLOB 'mcp__?*__?*' requires at least one char in both server and tool
        # segments — this correctly excludes mcp__notvalid, mcp____tool, and
        # mcp__server__ without needing a post-filter HAVING clause.
        where_parts = ["tool_name GLOB 'mcp__?*__?*'"]
        params: list[Any] = []
        if days is not None:
            where_parts.append("timestamp >= datetime('now', ?)")
            params.append(f"-{days} days")
        where = "WHERE " + " AND ".join(where_parts)
        cursor = await self._conn.execute(
            f"""SELECT
                substr(tool_name, 6, instr(substr(tool_name, 6), '__') - 1) AS server_name,
                count(distinct tool_name)                                    AS tool_count,
                count(*)                                                     AS call_count,
                sum(CASE WHEN status = 'success' THEN 1 ELSE 0 END)         AS success_count,
                avg(latency_ms)                                              AS avg_latency_ms
               FROM tool_calls
               {where}
               GROUP BY server_name
               ORDER BY call_count DESC""",  # noqa: S608
            params,
        )
        rows = await cursor.fetchall()
        return [
            MCPServerSummary(
                server_name=row["server_name"],
                tool_count=row["tool_count"],
                call_count=row["call_count"],
                success_count=row["success_count"],
                avg_latency_ms=row["avg_latency_ms"] or 0.0,
            )
            for row in rows
        ]

    async def list_mcp_tool_summaries(self, days: int | None = None) -> list[MCPToolSummary]:
        """Return per-tool stats for all tools whose name starts with mcp__."""
        assert self._conn is not None
        # GLOB 'mcp__?*__?*' requires at least one char in both server and tool
        # segments — this correctly excludes mcp__notvalid, mcp____tool, and
        # mcp__server__ without needing a post-filter HAVING clause.
        where_parts = ["tool_name GLOB 'mcp__?*__?*'"]
        params: list[Any] = []
        if days is not None:
            where_parts.append("timestamp >= datetime('now', ?)")
            params.append(f"-{days} days")
        where = "WHERE " + " AND ".join(where_parts)
        cursor = await self._conn.execute(
            f"""SELECT
                tool_name,
                substr(tool_name, 6, instr(substr(tool_name, 6), '__') - 1) AS server_name,
                count(*)                                                     AS call_count,
                sum(CASE WHEN status = 'success' THEN 1 ELSE 0 END)         AS success_count,
                avg(latency_ms)                                              AS avg_latency_ms
               FROM tool_calls
               {where}
               GROUP BY tool_name
               ORDER BY call_count DESC""",  # noqa: S608
            params,
        )
        rows = await cursor.fetchall()
        return [
            MCPToolSummary(
                tool_name=row["tool_name"],
                server_name=row["server_name"],
                call_count=row["call_count"],
                success_count=row["success_count"],
                avg_latency_ms=row["avg_latency_ms"] or 0.0,
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

    async def write_span(self, span_data: dict[str, Any]) -> None:
        """Persist an AgentSpanEvent to the agent_spans table."""
        assert self._conn is not None
        await self._conn.execute(
            """INSERT OR REPLACE INTO agent_spans (
                span_id, parent_span_id, trace_id, span_kind, agent_name,
                agent_role, started_at, ended_at, status, failure_type,
                token_input, token_output, tool_calls_count, llm_calls_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                span_data.get("span_id", ""),
                span_data.get("parent_span_id"),
                span_data.get("trace_id", ""),
                span_data.get("span_kind", "root"),
                span_data.get("agent_name", "unknown"),
                span_data.get("agent_role", ""),
                span_data.get("started_at", ""),
                span_data.get("ended_at"),
                span_data.get("status", "ok"),
                span_data.get("failure_type"),
                int(span_data.get("token_input", 0)),
                int(span_data.get("token_output", 0)),
                int(span_data.get("tool_calls_count", 0)),
                int(span_data.get("llm_calls_count", 0)),
            ),
        )
        await self._conn.commit()

    async def query_spans(self, trace_id: str) -> list[dict[str, Any]]:
        """Return all spans for a trace, ordered by started_at."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT * FROM agent_spans WHERE trace_id = ? ORDER BY started_at ASC",
            (trace_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def query_spans_all(self, limit: int = 5000) -> list[dict[str, Any]]:
        """Return all spans across all traces."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            "SELECT * FROM agent_spans ORDER BY started_at ASC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def list_traces(self, limit: int = 50, offset: int = 0) -> list[TraceSummary]:
        """Return one TraceSummary per trace_id, newest first."""
        assert self._conn is not None
        cursor = await self._conn.execute(
            """SELECT
                trace_id,
                min(CASE WHEN parent_span_id IS NULL THEN agent_name END) AS root_agent_name,
                count(*) AS span_count,
                sum(token_input) AS total_token_input,
                sum(token_output) AS total_token_output,
                min(started_at) AS started_at,
                min(CASE WHEN status = 'error' THEN 'error' ELSE 'ok' END) AS status
               FROM agent_spans
               GROUP BY trace_id
               ORDER BY started_at DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [
            TraceSummary(
                trace_id=row["trace_id"],
                root_agent_name=row["root_agent_name"] or "unknown",
                span_count=row["span_count"],
                total_token_input=row["total_token_input"] or 0,
                total_token_output=row["total_token_output"] or 0,
                started_at=row["started_at"] or "",
                status=row["status"] or "ok",
            )
            for row in rows
        ]

    async def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict[str, object]]:
        """Return sessions that have message events, newest first."""
        assert self._conn is not None
        async with self._conn.execute(
            """SELECT session_id, COUNT(*) as message_count,
                      MIN(timestamp) as first_seen, MAX(timestamp) as last_seen,
                      project, source
               FROM session_messages
               GROUP BY session_id
               ORDER BY last_seen DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ) as cur:
            rows = await cur.fetchall()
        return [
            {
                "session_id": r[0],
                "message_count": r[1],
                "first_seen": r[2],
                "last_seen": r[3],
                "project": r[4] or "",
                "source": r[5] or "",
            }
            for r in rows
        ]

    async def get_session_replay(self, session_id: str) -> list[dict[str, object]]:
        """Return all turns (messages + tool calls) for a session, ordered by timestamp."""
        assert self._conn is not None
        async with self._conn.execute(
            """SELECT 'message' AS kind, timestamp, role AS subtype,
                      content_preview, token_count, NULL, NULL, NULL
               FROM session_messages
               WHERE session_id = ?
               UNION ALL
               SELECT 'tool', timestamp, status,
                      NULL, NULL, tool_name, status, latency_ms
               FROM tool_calls
               WHERE session_id = ?
               ORDER BY timestamp ASC""",
            (session_id, session_id),
        ) as cur:
            rows = await cur.fetchall()
        turns: list[dict[str, object]] = []
        for r in rows:
            kind: str = r[0]
            if kind == "message":
                turns.append(
                    {
                        "kind": r[2],  # role → "user" or "assistant"
                        "timestamp": r[1],
                        "content_preview": r[3],
                        "token_count": r[4],
                        "tool_name": None,
                        "status": None,
                        "latency_ms": None,
                    }
                )
            else:
                turns.append(
                    {
                        "kind": "tool",
                        "timestamp": r[1],
                        "content_preview": None,
                        "token_count": None,
                        "tool_name": r[5],
                        "status": r[6],
                        "latency_ms": r[7],
                    }
                )
        return turns

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
