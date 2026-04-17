# Configuration

Anjor is configured via `.anjor.toml` in your project root, environment variables, or directly in code. Environment variables override `.anjor.toml`; code overrides both.

## `.anjor.toml` — full reference

```toml
# Path to the SQLite database.
# Default: ~/.anjor/anjor.db  (shared across all projects)
# Set a project-relative path to keep data separate per project.
db_path = "~/.anjor/anjor.db"

# Collector port
port = 7843

# Batch write settings — events are buffered and written in batches
batch_size = 50
batch_interval_ms = 500

# Log level: DEBUG | INFO | WARNING | ERROR
log_level = "INFO"

# Maximum allowed payload size for POST /events
max_payload_size_kb = 512

# Rate limiting for POST /events (0 = disabled)
rate_limit_rps = 500
rate_limit_burst = 1000

# Conversation capture — stores first 500 chars of each turn locally
# On by default. Disable if you don't need Session Replay.
capture_messages = true

# OTel export — ship spans to Jaeger, Grafana Tempo, Datadog Agent, etc.
[export]
otlp_endpoint = "http://localhost:4318"      # OTLP/HTTP JSON
# otlp_headers = { "x-api-key" = "..." }    # optional auth headers

# Alerts — fire webhooks when conditions are breached
[[alerts]]
name        = "high_failure_rate"
condition   = "failure_rate > 0.20"
window_calls = 10                            # rolling window of last N tool calls
webhook     = "https://hooks.slack.com/services/..."

[[alerts]]
name      = "context_warning"
condition = "context_utilisation > 0.80"
webhook   = "https://hooks.slack.com/services/..."

[[alerts]]
name      = "daily_budget"
condition = "daily_cost_usd > 5.00"
webhook   = "https://example.com/webhook"
```

## Environment variables

All settings can be overridden with `ANJOR_` prefixed environment variables:

```bash
ANJOR_DB_PATH=./project.db
ANJOR_PORT=7843
ANJOR_BATCH_SIZE=1
ANJOR_BATCH_INTERVAL_MS=100
ANJOR_LOG_LEVEL=DEBUG
ANJOR_MAX_PAYLOAD_SIZE_KB=512
ANJOR_CAPTURE_MESSAGES=false
```

## Code configuration

```python
import anjor
from anjor.core.config import AnjorConfig

anjor.patch(config=AnjorConfig(
    db_path="project.db",
    batch_size=1,
    capture_messages=False,
))
```

## Disabling message capture

Session Replay requires message capture, which is on by default. To opt out:

```toml
# .anjor.toml
capture_messages = false
```

Or at runtime:
```bash
anjor start --no-capture-messages
anjor mcp --no-capture-messages
anjor watch-transcripts --no-capture-messages
```

## Project tagging

Tag events with a project name to filter the dashboard per project:

```bash
anjor start --watch-transcripts --project myapp
```

Or set it in config:
```toml
# .anjor.toml
project = "myapp"
```

The dashboard's project selector then filters all pages to that project's data.
