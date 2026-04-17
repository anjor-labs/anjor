-- Session-level metadata: archive flag and project override.
-- Independent of session_messages so sessions with only tool/LLM events are also covered.
CREATE TABLE IF NOT EXISTS session_metadata (
    session_id   TEXT    PRIMARY KEY,
    archived     INTEGER NOT NULL DEFAULT 0,
    project      TEXT    NOT NULL DEFAULT '',
    updated_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_session_metadata_archived ON session_metadata(archived);
