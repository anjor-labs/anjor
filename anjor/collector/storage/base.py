"""StorageBackend ABC — contract for all storage implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class QueryFilters:
    """Filters for querying tool call events."""

    tool_name: str | None = None
    status: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 100
    offset: int = 0


@dataclass(frozen=True)
class SchemaSnapshot:
    """Snapshot of a tool's input or output schema fingerprint."""

    tool_name: str
    payload_type: str  # "input" or "output"
    schema_hash: str
    captured_at: datetime
    sample_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMQueryFilters:
    """Filters for querying LLM call events."""

    trace_id: str | None = None
    agent_id: str | None = None
    model: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 100
    offset: int = 0


@dataclass
class LLMSummary:
    """Aggregated stats for a model."""

    model: str
    call_count: int
    avg_latency_ms: float
    avg_token_input: float
    avg_token_output: float
    avg_context_utilisation: float


@dataclass
class ToolSummary:
    """Aggregated stats for a single tool."""

    tool_name: str
    call_count: int
    success_count: int
    failure_count: int
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float

    @property
    def success_rate(self) -> float:
        if self.call_count == 0:
            return 0.0
        return self.success_count / self.call_count


class StorageBackend(ABC):
    """Abstract storage backend. Swap SQLite → Postgres by implementing this."""

    @abstractmethod
    async def write_event(self, event_data: dict[str, Any]) -> None:
        """Persist a single event (serialised dict). Routes by event_type."""
        ...

    @abstractmethod
    async def write_llm_event(self, event_data: dict[str, Any]) -> None:
        """Persist an LLM call event to the llm_calls table."""
        ...

    @abstractmethod
    async def query_llm_calls(
        self, filters: LLMQueryFilters
    ) -> list[dict[str, Any]]:
        """Query stored LLM call events with optional filters."""
        ...

    @abstractmethod
    async def list_llm_summaries(self) -> list[LLMSummary]:
        """Return aggregated stats per model."""
        ...

    @abstractmethod
    async def query_tool_calls(
        self, filters: QueryFilters
    ) -> list[dict[str, Any]]:
        """Query stored tool call events with optional filters."""
        ...

    @abstractmethod
    async def get_tool_summary(self, tool_name: str) -> ToolSummary | None:
        """Return aggregated stats for a tool."""
        ...

    @abstractmethod
    async def list_tool_summaries(self) -> list[ToolSummary]:
        """Return aggregated stats for all tools."""
        ...

    @abstractmethod
    async def write_schema_snapshot(self, snap: SchemaSnapshot) -> None:
        """Persist a schema fingerprint snapshot."""
        ...

    @abstractmethod
    async def get_schema_snapshot(
        self, tool_name: str, payload_type: str
    ) -> SchemaSnapshot | None:
        """Retrieve the latest snapshot for a tool + payload_type pair."""
        ...

    @abstractmethod
    async def query_tool_calls_for_analysis(
        self, tool_name: str | None = None, limit: int = 2000
    ) -> list[dict[str, Any]]:
        """Return raw tool call rows for intelligence analysis (Phase 3).

        Higher default limit than query_tool_calls so analysers see enough history.
        """
        ...

    @abstractmethod
    async def query_drift_summary(self) -> list[dict[str, Any]]:
        """Return per-tool drift counts: tool_name, total_calls, drift_calls."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources."""
        ...
