-- Migration 007: add session_messages table for opt-in conversation capture
CREATE TABLE IF NOT EXISTS session_messages (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT    NOT NULL,
    trace_id       TEXT    NOT NULL DEFAULT '',
    agent_id       TEXT    NOT NULL DEFAULT 'default',
    timestamp      TEXT    NOT NULL,
    turn_index     INTEGER NOT NULL DEFAULT 0,
    role           TEXT    NOT NULL CHECK(role IN ('user', 'assistant')),
    content_preview TEXT   NOT NULL DEFAULT '',
    token_count    INTEGER,
    source         TEXT    NOT NULL DEFAULT '',
    project        TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_session_messages_session   ON session_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_session_messages_timestamp ON session_messages(timestamp);
