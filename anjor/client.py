"""Programmatic Python query client for Anjor.

Reads SQLite directly — no collector process required.

Usage::

    import anjor

    client = anjor.Client("anjor.db")
    tools = client.tools()                        # list[ToolSummary]
    tool  = client.tool("web_search")             # ToolSummary | None
    calls = client.calls(limit=50)                # list[ToolCallRecord]
    failures = client.intelligence.failures()     # list[FailurePattern]
    quality  = client.intelligence.quality()      # list[ToolQualityScore]
    runs     = client.intelligence.run_quality()  # list[RunQualityScore]
    opts     = client.intelligence.optimization() # list[OptimizationSuggestion]
    client.close()

    # Or as a context manager:
    with anjor.Client("anjor.db") as client:
        print(client.tools())
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime
from typing import Any, TypeVar

from anjor.collector.storage.base import LLMQueryFilters, QueryFilters
from anjor.collector.storage.sqlite import SQLiteBackend
from anjor.models import (
    FailurePattern,
    OptimizationSuggestion,
    RunQualityScore,
    ToolCallRecord,
    ToolQualityScore,
    ToolSummary,
)

_T = TypeVar("_T")

__all__ = ["Client"]


class _IntelligenceClient:
    """Namespace for intelligence queries (``client.intelligence.*``)."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def failures(self) -> list[FailurePattern]:
        """Return failure clusters sorted by failure rate descending."""
        from anjor.analysis.intelligence.failure_clustering import FailureClusterer

        tool_calls = self._client._run(self._client._storage().query_tool_calls_for_analysis())
        clusterer = FailureClusterer()
        clusters = clusterer.cluster(tool_calls)
        return [
            FailurePattern(
                tool_name=c.tool_name,
                failure_type=c.failure_type,
                occurrence_count=c.occurrence_count,
                total_calls=c.total_calls,
                failure_rate=c.failure_rate,
                avg_latency_ms=c.avg_latency_ms,
                pattern_description=c.pattern_description,
                suggestion=c.suggestion,
                example_trace_ids=c.example_trace_ids,
            )
            for c in clusters
        ]

    def quality(self) -> list[ToolQualityScore]:
        """Return per-tool quality scores, worst first."""
        from anjor.analysis.intelligence.quality_scorer import QualityScorer

        tool_calls = self._client._run(self._client._storage().query_tool_calls_for_analysis())
        scorer = QualityScorer()
        scores = scorer.score_tools(tool_calls)
        return [
            ToolQualityScore(
                tool_name=s.tool_name,
                call_count=s.call_count,
                reliability_score=s.reliability_score,
                schema_stability_score=s.schema_stability_score,
                latency_consistency_score=s.latency_consistency_score,
                overall_score=s.overall_score,
                grade=s.grade,
            )
            for s in scores
        ]

    def run_quality(self) -> list[RunQualityScore]:
        """Return per-run (trace) quality scores, worst first."""
        from anjor.analysis.intelligence.quality_scorer import QualityScorer

        storage = self._client._storage()
        tool_calls = self._client._run(storage.query_tool_calls_for_analysis())
        llm_calls = self._client._run(storage.query_llm_calls(LLMQueryFilters(limit=2000)))
        scorer = QualityScorer()
        scores = scorer.score_runs(tool_calls, llm_calls)
        return [
            RunQualityScore(
                trace_id=s.trace_id,
                llm_call_count=s.llm_call_count,
                tool_call_count=s.tool_call_count,
                context_efficiency_score=s.context_efficiency_score,
                failure_recovery_score=s.failure_recovery_score,
                tool_diversity_score=s.tool_diversity_score,
                overall_score=s.overall_score,
                grade=s.grade,
            )
            for s in scores
        ]

    def optimization(self) -> list[OptimizationSuggestion]:
        """Return token optimization suggestions for context-bloating tools."""
        from anjor.analysis.intelligence.token_optimizer import TokenOptimizer

        storage = self._client._storage()
        tool_calls = self._client._run(storage.query_tool_calls_for_analysis())
        llm_calls = self._client._run(storage.query_llm_calls(LLMQueryFilters(limit=2000)))
        optimizer = TokenOptimizer()
        suggestions = optimizer.optimize(tool_calls, llm_calls)
        return [
            OptimizationSuggestion(
                tool_name=s.tool_name,
                avg_output_tokens=s.avg_output_tokens,
                avg_context_fraction=s.avg_context_fraction,
                waste_score=s.waste_score,
                estimated_savings_tokens_per_call=s.estimated_savings_tokens_per_call,
                estimated_savings_usd_per_1k_calls=s.estimated_savings_usd_per_1k_calls,
                suggestion_text=s.suggestion_text,
                sample_models=s.sample_models,
            )
            for s in suggestions
        ]


class Client:
    """Read-only programmatic client for Anjor data.

    Reads the SQLite database directly — the anjor collector does not need to
    be running.  Connection is opened lazily on first query.

    Args:
        db_path: Path to the anjor SQLite database (default: ``"anjor.db"``).

    Example::

        with anjor.Client("anjor.db") as client:
            for t in client.tools():
                print(t.tool_name, t.success_rate)
    """

    def __init__(self, db_path: str = "anjor.db") -> None:
        self._db_path = db_path
        self._backend: SQLiteBackend | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.intelligence = _IntelligenceClient(self)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _storage(self) -> SQLiteBackend:
        """Return (creating + connecting lazily) the SQLiteBackend."""
        if self._backend is None:
            self._loop = asyncio.new_event_loop()
            backend = SQLiteBackend(
                db_path=self._db_path,
                batch_size=1,
                batch_interval_ms=9_999_999,  # effectively disabled for read-only use
            )
            self._loop.run_until_complete(backend.connect())
            self._backend = backend
        return self._backend

    def _run(self, coro: Coroutine[Any, Any, _T]) -> _T:
        """Run *coro* on the client's dedicated event loop (sync bridge)."""
        assert self._loop is not None
        return self._loop.run_until_complete(coro)

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    def tools(self) -> list[ToolSummary]:
        """Return summary stats for every tool that has been called at least once."""
        storage_summaries = self._run(self._storage().list_tool_summaries())
        return [
            ToolSummary(
                tool_name=s.tool_name,
                call_count=s.call_count,
                success_count=s.success_count,
                failure_count=s.failure_count,
                success_rate=s.success_rate,
                avg_latency_ms=s.avg_latency_ms,
                p50_latency_ms=s.p50_latency_ms,
                p95_latency_ms=s.p95_latency_ms,
                p99_latency_ms=s.p99_latency_ms,
            )
            for s in storage_summaries
        ]

    def tool(self, name: str) -> ToolSummary | None:
        """Return summary stats for a single tool, or ``None`` if never called."""
        s = self._run(self._storage().get_tool_summary(name))
        if s is None:
            return None
        return ToolSummary(
            tool_name=s.tool_name,
            call_count=s.call_count,
            success_count=s.success_count,
            failure_count=s.failure_count,
            success_rate=s.success_rate,
            avg_latency_ms=s.avg_latency_ms,
            p50_latency_ms=s.p50_latency_ms,
            p95_latency_ms=s.p95_latency_ms,
            p99_latency_ms=s.p99_latency_ms,
        )

    def calls(
        self,
        *,
        tool_name: str | None = None,
        status: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ToolCallRecord]:
        """Return raw tool call records matching the given filters.

        Args:
            tool_name: Filter by exact tool name.
            status: ``"success"`` or ``"failure"``.
            since: Include only calls at or after this UTC datetime.
            until: Include only calls at or before this UTC datetime.
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (for pagination).
        """
        filters = QueryFilters(
            tool_name=tool_name,
            status=status,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )
        rows = self._run(self._storage().query_tool_calls(filters))
        return [
            ToolCallRecord(
                tool_name=row["tool_name"],
                status=row["status"],
                failure_type=row.get("failure_type"),
                latency_ms=row["latency_ms"],
                trace_id=row["trace_id"],
                session_id=row["session_id"],
                agent_id=row["agent_id"],
                timestamp=row["timestamp"],
                input_schema_hash=row.get("input_schema_hash") or "",
                output_schema_hash=row.get("output_schema_hash") or "",
                drift_detected=bool(row["drift_detected"])
                if row.get("drift_detected") is not None
                else None,
            )
            for row in rows
        ]

    def close(self) -> None:
        """Close the database connection and release resources."""
        if self._backend is not None and self._loop is not None:
            self._loop.run_until_complete(self._backend.close())
            self._loop.close()
            self._backend = None
            self._loop = None

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
