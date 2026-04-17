# Intelligence Features

Anjor's intelligence layer analyses historical event data to surface patterns and actionable recommendations. All analysis runs on your local data — no external API calls.

Access via the dashboard at `/ui/intelligence.html` or the REST API.

---

## Root Cause Hypotheses

`GET /intelligence/root_causes`

Generates ranked hypotheses from 6 automated rules. Each hypothesis has a confidence level (high / medium / low), supporting evidence, and a recommended action.

| Rule | Triggers when |
|------|--------------|
| **Timeout pattern** | A tool has >10% timeout failure rate |
| **Schema drift + failure** | A tool has >10% drift rate AND <90% success rate |
| **Dominant failure tool** | One tool accounts for >50% of all failures |
| **Context window pressure** | Any model averages >75% context utilisation while failures are present |
| **High latency variance** | A tool's p95 latency is >3× its average (min 5 calls) |
| **Retry storm** | A tool's call count is >5× the per-tool average and it's the top failure tool |

Confidence levels: `high` = structural problem (schema drift, dominant failures, timeouts); `medium` = likely correlated; `low` = circumstantial.

---

## Failure Patterns

`GET /intelligence/failures`

Groups tool failures by `(tool_name, failure_type)`. Each cluster includes:
- Failure rate and occurrence count
- Natural-language pattern description
- Suggested fix
- Example trace IDs for drill-down

---

## Token Optimization

`GET /intelligence/optimization`

Identifies tools whose average output size exceeds 5% of the model's context window. Reports:
- Average output token count and context fraction
- Waste score (0–100%)
- Estimated cost savings per 1,000 calls
- Concrete suggestion (e.g. "add `max_results=5` to web_search")

---

## Tool Quality Scores

`GET /intelligence/quality/tools`

Grades each tool A–F based on three measurable signals:

| Signal | What it measures |
|--------|-----------------|
| **Reliability** | 1 − failure rate |
| **Schema stability** | 1 − drift rate (how often input/output structure changes) |
| **Latency consistency** | Inverse of coefficient of variation (p95/avg ratio) |

Overall score is a weighted average. Sorted worst-first so you see what needs attention immediately.

---

## Agent Run Quality

`GET /intelligence/quality/runs`

Grades each agent run (trace_id) A–F based on:

| Signal | What it measures |
|--------|-----------------|
| **Context efficiency** | Inverse of average context utilisation |
| **Failure recovery** | Whether failures occur early vs. throughout the run |
| **Tool diversity** | How varied the tool usage is (single-tool runs score lower) |

---

## Prompt Version Tracking

`GET /intelligence/prompt_versions`

Groups LLM calls by `system_prompt_hash` — a SHA-256 fingerprint of the system prompt. For each version shows:
- First and last seen dates
- Call count
- Average input tokens and context utilisation
- Models used

Useful for correlating prompt changes with quality changes. The actual prompt text is never stored — only its hash.

---

## Attribution

`GET /intelligence/attribution`

Token and failure attribution per agent (for multi-agent traces):
- Total token consumption (input + output)
- Share of total tokens (%)
- Tool call count, LLM call count, failure count, failure rate

Useful for understanding which agent in a multi-agent system is consuming resources or causing failures.
