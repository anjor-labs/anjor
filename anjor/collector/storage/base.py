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
    project: str | None = None
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
    project: str | None = None
    limit: int = 100
    offset: int = 0


@dataclass
class ProjectSummary:
    """Aggregated stats for a single project tag."""

    project: str
    tool_call_count: int
    llm_call_count: int
    total_token_input: int
    total_token_output: int
    first_seen: str
    last_seen: str


@dataclass
class TraceSummary:
    """Top-level summary of a single trace (for the traces list view)."""

    trace_id: str
    root_agent_name: str
    span_count: int
    total_token_input: int
    total_token_output: int
    started_at: str
    status: str  # "ok" if all spans ok, else "error"


@dataclass
class LLMSummary:
    """Aggregated stats for a model."""

    model: str
    call_count: int
    avg_latency_ms: float
    avg_token_input: float
    avg_token_output: float
    avg_context_utilisation: float
    total_token_input: int = 0
    total_token_output: int = 0
    total_cache_read: int = 0
    total_cache_write: int = 0
    source: str = ""


@dataclass
class MCPServerSummary:
    """Aggregated stats for an MCP server (tools grouped by mcp__<server>__ prefix)."""

    server_name: str
    tool_count: int
    call_count: int
    success_count: int
    avg_latency_ms: float

    @property
    def success_rate(self) -> float:
        if self.call_count == 0:
            return 0.0
        return self.success_count / self.call_count


@dataclass
class MCPToolSummary:
    """Aggregated stats for a single MCP tool."""

    tool_name: str  # full name, e.g. mcp__github__create_pr
    server_name: str  # extracted middle segment, e.g. github
    call_count: int
    success_count: int
    avg_latency_ms: float

    @property
    def success_rate(self) -> float:
        if self.call_count == 0:
            return 0.0
        return self.success_count / self.call_count

    @property
    def short_name(self) -> str:
        """Tool name with mcp__<server>__ prefix stripped."""
        prefix = f"mcp__{self.server_name}__"
        return (
            self.tool_name[len(prefix) :] if self.tool_name.startswith(prefix) else self.tool_name
        )


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
    async def query_llm_calls(self, filters: LLMQueryFilters) -> list[dict[str, Any]]:
        """Query stored LLM call events with optional filters."""
        ...

    @abstractmethod
    async def list_llm_summaries(
        self,
        days: int | None = None,
        project: str | None = None,
        since_minutes: int | None = None,
    ) -> list[LLMSummary]:
        """Return aggregated stats per model, optionally limited to the last N days or N minutes."""
        ...

    @abstractmethod
    async def list_daily_usage(
        self, days: int = 14, project: str | None = None
    ) -> list[dict[str, Any]]:
        """Return token usage grouped by date and model for the last N days."""
        ...

    @abstractmethod
    async def query_llm_sources(self) -> list[str]:
        """Return a list of unique source tags from the llm_calls table."""
        ...

    @abstractmethod
    async def query_tool_calls(self, filters: QueryFilters) -> list[dict[str, Any]]:
        """Query stored tool call events with optional filters."""
        ...

    @abstractmethod
    async def get_tool_summary(
        self,
        tool_name: str,
        project: str | None = None,
        since_minutes: int | None = None,
    ) -> ToolSummary | None:
        """Return aggregated stats for a tool, optionally scoped to a project and time window."""
        ...

    @abstractmethod
    async def list_tool_summaries(
        self,
        project: str | None = None,
        since_minutes: int | None = None,
    ) -> list[ToolSummary]:
        """Return aggregated stats for all tools, optionally scoped to project and time window."""
        ...

    @abstractmethod
    async def list_mcp_server_summaries(self, days: int | None = None) -> list[MCPServerSummary]:
        """Return per-server aggregated stats for all MCP tools (mcp__<server>__ prefix)."""
        ...

    @abstractmethod
    async def list_mcp_tool_summaries(self, days: int | None = None) -> list[MCPToolSummary]:
        """Return per-tool aggregated stats for all MCP tools."""
        ...

    @abstractmethod
    async def write_schema_snapshot(self, snap: SchemaSnapshot) -> None:
        """Persist a schema fingerprint snapshot."""
        ...

    @abstractmethod
    async def get_schema_snapshot(self, tool_name: str, payload_type: str) -> SchemaSnapshot | None:
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
    async def write_span(self, span_data: dict[str, Any]) -> None:
        """Persist a single AgentSpanEvent dict to the agent_spans table."""
        ...

    @abstractmethod
    async def query_spans(self, trace_id: str) -> list[dict[str, Any]]:
        """Return all spans for a given trace_id, ordered by started_at."""
        ...

    @abstractmethod
    async def query_spans_all(self, limit: int = 5000) -> list[dict[str, Any]]:
        """Return all spans across all traces (for global attribution)."""
        ...

    @abstractmethod
    async def list_projects(self) -> list[ProjectSummary]:
        """Return per-project aggregated stats from tool_calls and llm_calls."""
        ...

    @abstractmethod
    async def list_traces(self, limit: int = 50, offset: int = 0) -> list[TraceSummary]:
        """Return one TraceSummary per trace_id, newest first."""
        ...

    @abstractmethod
    async def flush(self) -> int:
        """Force-flush all pending batch writes immediately.

        Returns the number of events written in this flush.  Useful in
        development and tests to make just-written events immediately queryable
        without waiting for the periodic batch interval.
        """
        ...

    @abstractmethod
    async def connect(self) -> None:
        """Open the connection / run migrations."""
        ...

    @abstractmethod
    async def list_prompt_versions(
        self, project: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return LLM calls grouped by system_prompt_hash, newest first."""
        ...

    @abstractmethod
    async def save_baseline(self, name: str, window: str, metrics_json: str) -> None:
        """Upsert a named diff baseline."""
        ...

    @abstractmethod
    async def load_baseline(self, name: str) -> dict[str, Any] | None:
        """Return a named baseline, or None if not found."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources."""
        ...
