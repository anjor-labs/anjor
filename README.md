# Anjor

[![CI](https://github.com/anjor-labs/anjor/actions/workflows/ci.yml/badge.svg)](https://github.com/anjor-labs/anjor/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-97%25-brightgreen)](https://github.com/anjor-labs/anjor)
[![PyPI](https://img.shields.io/pypi/v/anjor)](https://pypi.org/project/anjor/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

AI agents fail silently. A tool times out, a schema drifts, the context window fills up — and you find out from a user complaint, not a dashboard.

Anjor fixes that. It intercepts your agent's HTTP traffic at the protocol layer and gives you full visibility into every LLM call and tool use — latency, token usage, context window growth, schema drift, prompt changes — without changing a single line of your agent code. Beyond passive logging, it surfaces actionable intelligence: failure pattern clustering, token optimization suggestions, and per-tool quality grades (A–F).

One-line install. No cloud. No account required.

---

## Install

```bash
pip install anjor
```

---

## Quickstart

**1. Start the collector and dashboard** (one command, one port):

```bash
anjor start
# Anjor collector  http://localhost:7843/health
# Anjor dashboard  http://localhost:7843/ui/
```

**2. Add one line to your agent:**

```python
import anjor
anjor.patch()   # that's it — httpx is now instrumented

import anthropic
client = anthropic.Anthropic()
# make calls as normal — they're captured automatically
```

Open `http://localhost:7843/ui/` to see the dashboard.

**3. Query the API directly:**

```bash
curl http://localhost:7843/health
curl http://localhost:7843/tools
curl http://localhost:7843/intelligence/failures
curl http://localhost:7843/intelligence/quality/tools
```

---

## What it captures

| Signal | Details |
|--------|---------|
| Tool calls | Name, status (success/failure), failure type |
| Schema fingerprints | SHA-256 structural hash of tool input/output shape |
| Schema drift | Field-level diff against the baseline for each tool |
| Latency | Per-call and aggregated (p50/p95/p99) |
| LLM calls | Model, latency, finish reason — Anthropic, OpenAI, and Gemini |
| Token usage | Input + output + cache_read tokens per call |
| Context window | Tokens used vs model limit, utilisation %, per-trace growth |
| Context hogs | Per-tool average output size, % of context consumed |
| System prompt drift | SHA-256 per agent — alerts when prompt changes between calls |
| Failure patterns | Clustered failure analysis with descriptions and fix suggestions |
| Token optimization | Tools consuming >5% of context window, cost savings estimates |
| Quality scores | Per-tool reliability/schema-stability/latency grade (A–F) |
| Run quality | Per-trace context efficiency, failure recovery, diversity grade |
| Multi-agent spans | Parent/child span linking across agent boundaries |
| Trace graphs | DAG reconstruction, topological order, cycle detection |
| Cross-agent attribution | Token usage and failure rate broken down per agent |

---

## Supported providers

| Provider | SDK | Intercepted endpoint |
|----------|-----|----------------------|
| Anthropic | `anthropic` | `api.anthropic.com/v1/messages` |
| OpenAI | `openai` | `api.openai.com/v1/chat/completions` |
| Google Gemini | `google-generativeai` | `generativelanguage.googleapis.com/.../generateContent` |

All three providers are auto-detected — no configuration required.

---

## Configuration

Via environment variables:

```bash
ANJOR_DB_PATH=./my_project.db python my_agent.py
ANJOR_BATCH_SIZE=1 ANJOR_BATCH_INTERVAL_MS=100 python my_agent.py
ANJOR_LOG_LEVEL=DEBUG python my_agent.py
```

Via `.anjor.toml` in your project root:

```toml
db_path = "my_project.db"
batch_size = 10
batch_interval_ms = 200
log_level = "DEBUG"
```

Via code:

```python
import anjor
from anjor.core.config import AnjorConfig

anjor.patch(config=AnjorConfig(db_path="my_project.db", batch_size=1))
```

---

## Limitations

- `requests` library not intercepted — all three provider SDKs use httpx by default
- Streaming responses are not parsed; only non-streaming calls are captured
- No cloud sync, authentication, or team features

---

## Development

```bash
git clone https://github.com/anjor-labs/anjor.git
cd anjor
pip install -e ".[dev]"
pytest --cov=anjor --cov-fail-under=95 -q
ruff check anjor/ tests/
mypy anjor/
anjor start
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidelines.

---

## Documentation

- [Quickstart — see it in action](docs/quickstart.md)
- [Architecture — layer diagram and design decisions](docs/architecture.md)

---

## Contributing & Contact

- **Bug reports / feature requests** — [open an issue](https://github.com/anjor-labs/anjor/issues)
- **Questions / ideas** — [start a discussion](https://github.com/anjor-labs/anjor/discussions)

## License

[MIT](LICENSE) © Anjor Labs
