# anjor/analysis

Pure analysis components — no I/O, no side effects.

## Modules

- **`drift/fingerprint.py`** — `fingerprint(payload)`: SHA-256 of structural shape (keys+types, not values). `diff_schemas()`: field-level diff.
- **`drift/detector.py`** — `DriftDetector`: per-tool baseline, returns `SchemaDrift` on change.
- **`classification/failure.py`** — `FailureClassifier`: priority-ordered rule chain (Timeout→SchemaDrift→APIError→Unknown). Pluggable rules.
- **`base.py`** — `BaseAnalyser` ABC.

## Architecture fit

Analysers are called by the collector or interceptor layer. They never write to storage or call external services — they return data structures that callers can persist.

## Extension

New classification rule: subclass `BaseRule`, set a priority, pass to `FailureClassifier(rules=[...])`.
