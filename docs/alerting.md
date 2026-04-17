# Alerting & Budgeting

Configure threshold alerts in `.anjor.toml`. Anjor evaluates conditions on every ingested event and fires a webhook when a condition is breached. Silent by default — you only hear from it when something matters.

## Configuration

```toml
[[alerts]]
name        = "high_failure_rate"
condition   = "failure_rate > 0.20"
window_calls = 10                            # rolling window of last N tool calls
webhook     = "https://hooks.slack.com/services/T.../B.../..."

[[alerts]]
name      = "context_warning"
condition = "context_utilisation > 0.80"
webhook   = "https://hooks.slack.com/services/..."

[[alerts]]
name      = "daily_budget"
condition = "daily_cost_usd > 5.00"
webhook   = "https://example.com/my-webhook"
```

## Supported conditions

| Condition | Triggers when |
|-----------|--------------|
| `failure_rate > N` | Rolling window of tool calls exceeds failure rate N (0.0–1.0) |
| `p95_latency > N` | p95 latency in rolling window exceeds N milliseconds |
| `context_utilisation > N` | Any LLM call uses more than N fraction of context window (0.0–1.0) |
| `daily_cost_usd > N` | Cumulative estimated cost today exceeds $N |
| `session_cost_usd > N` | Cumulative cost since collector started exceeds $N |
| `error_type == "timeout"` | Any tool call fails with the specified failure type |

## Webhook payload

```json
{
  "alert": "daily_budget",
  "value": 5.21,
  "threshold": 5.00,
  "timestamp": "2026-04-17T14:32:00Z"
}
```

## Slack integration

When the webhook URL contains `hooks.slack.com`, Anjor automatically formats the payload as:

```json
{"text": "anjor alert: daily_budget — value 5.21 exceeded threshold 5.00"}
```

No extra configuration needed — just paste your Slack incoming webhook URL.

## Notes

- Webhook dispatch is fire-and-forget — failures are logged but never block event ingestion.
- Cost estimates use a built-in price table (manually maintained). Token counts are exact; dollar figures are approximate.
- `window_calls` applies to `failure_rate` and `p95_latency` conditions only. Other conditions use absolute accumulators.
