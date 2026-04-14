-- Migration 002: LLM call tracing (Phase 2)
-- Adds llm_calls and prompt_snapshots tables.
-- No SQLite-specific functions used — designed for Postgres compatibility.

CREATE TABLE IF NOT EXISTS llm_calls (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id              TEXT    NOT NULL,
    session_id            TEXT    NOT NULL,
    agent_id              TEXT    NOT NULL DEFAULT 'default',
    timestamp             TEXT    NOT NULL,
    sequence_no           INTEGER NOT NULL DEFAULT 0,
    model                 TEXT    NOT NULL,
    latency_ms            REAL    NOT NULL,
    token_input           INTEGER,
    token_output          INTEGER,
    token_cache_read      INTEGER,
    token_cache_write     INTEGER,
    context_window_used   INTEGER,
    context_window_limit  INTEGER,
    context_utilisation   REAL,
    prompt_hash           TEXT,
    system_prompt_hash    TEXT,
    messages_count        INTEGER,
    finish_reason         TEXT
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_trace_id    ON llm_calls (trace_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_agent_id    ON llm_calls (agent_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_model       ON llm_calls (model);
CREATE INDEX IF NOT EXISTS idx_llm_calls_timestamp   ON llm_calls (timestamp);

-- prompt_snapshots: one row per (agent_id, system_prompt_hash) pair.
-- Tracks when a system prompt was first seen and how many calls have used it.
CREATE TABLE IF NOT EXISTS prompt_snapshots (
    agent_id            TEXT    NOT NULL,
    system_prompt_hash  TEXT    NOT NULL,
    first_seen          TEXT    NOT NULL,
    last_seen           TEXT    NOT NULL,
    call_count          INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (agent_id, system_prompt_hash)
);
