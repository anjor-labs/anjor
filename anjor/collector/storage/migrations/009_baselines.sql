CREATE TABLE IF NOT EXISTS baselines (
    name TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    window TEXT NOT NULL,
    metrics_json TEXT NOT NULL
);
