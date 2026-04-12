CREATE TABLE IF NOT EXISTS agent_spans (
    span_id          TEXT PRIMARY KEY,
    parent_span_id   TEXT,
    trace_id         TEXT NOT NULL,
    span_kind        TEXT NOT NULL DEFAULT 'root',
    agent_name       TEXT NOT NULL DEFAULT 'unknown',
    agent_role       TEXT NOT NULL DEFAULT '',
    started_at       TEXT NOT NULL DEFAULT '',
    ended_at         TEXT,
    status           TEXT NOT NULL DEFAULT 'ok',
    failure_type     TEXT,
    token_input      INTEGER NOT NULL DEFAULT 0,
    token_output     INTEGER NOT NULL DEFAULT 0,
    tool_calls_count INTEGER NOT NULL DEFAULT 0,
    llm_calls_count  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_agent_spans_trace_id ON agent_spans (trace_id);
