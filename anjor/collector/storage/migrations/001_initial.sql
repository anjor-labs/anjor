-- Migration 001: Initial schema
-- Tables: tool_calls, schema_snapshots, drift_events
-- Designed for Postgres compatibility (no SQLite-specific functions in app queries)

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type          TEXT    NOT NULL,
    trace_id            TEXT    NOT NULL,
    session_id          TEXT    NOT NULL,
    agent_id            TEXT    NOT NULL DEFAULT 'default',
    timestamp           TEXT    NOT NULL,
    sequence_no         INTEGER NOT NULL DEFAULT 0,
    tool_name           TEXT    NOT NULL,
    status              TEXT    NOT NULL,
    failure_type        TEXT,
    latency_ms          REAL    NOT NULL,
    input_payload       TEXT    NOT NULL DEFAULT '{}',
    output_payload      TEXT    NOT NULL DEFAULT '{}',
    input_schema_hash   TEXT    NOT NULL DEFAULT '',
    output_schema_hash  TEXT    NOT NULL DEFAULT '',
    token_usage_input   INTEGER,
    token_usage_output  INTEGER,
    drift_detected      INTEGER,
    drift_missing       TEXT,
    drift_unexpected    TEXT,
    drift_expected_hash TEXT,
    source              TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_tool_name  ON tool_calls (tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_calls_status     ON tool_calls (status);
CREATE INDEX IF NOT EXISTS idx_tool_calls_timestamp  ON tool_calls (timestamp);
CREATE INDEX IF NOT EXISTS idx_tool_calls_trace_id   ON tool_calls (trace_id);

CREATE TABLE IF NOT EXISTS schema_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name       TEXT NOT NULL,
    payload_type    TEXT NOT NULL,   -- 'input' or 'output'
    schema_hash     TEXT NOT NULL,
    captured_at     TEXT NOT NULL,
    sample_payload  TEXT NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_schema_snapshots_unique
    ON schema_snapshots (tool_name, payload_type);

CREATE TABLE IF NOT EXISTS drift_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name       TEXT NOT NULL,
    detected_at     TEXT NOT NULL,
    expected_hash   TEXT NOT NULL,
    actual_hash     TEXT NOT NULL,
    missing_fields  TEXT NOT NULL DEFAULT '[]',
    unexpected_fields TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_drift_events_tool_name ON drift_events (tool_name);
