# Anjor

[![CI](https://github.com/anjor-labs/anjor/actions/workflows/ci.yml/badge.svg)](https://github.com/anjor-labs/anjor/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-97%25-brightgreen)](https://github.com/anjor-labs/anjor)
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
# Database         anjor.db
```

**2. Add one line to your agent:**

```python
import anjor
anjor.patch()   # that's it — httpx is now instrumented

import anthropic
client = anthropic.Anthropic()
# make tool calls as normal — they're captured automatically
```

Open `http://localhost:7843/ui/` in your browser to see the dashboard.

**3. Query the API directly:**

```bash
curl http://localhost:7843/health
curl http://localhost:7843/tools
curl http://localhost:7843/intelligence/failures
curl http://localhost:7843/intelligence/quality/tools
```

No API key? Use [`respx`](https://lundberg.github.io/respx/) to replay a mock response — see the [quickstart guide](docs/quickstart.md).

---

## What it captures

| Signal | Phase | Details |
|--------|-------|---------|
| Tool calls | 1 | Name, status (success/failure), failure type |
| Schema fingerprints | 1 | SHA-256 structural hash of tool input/output shape |
| Schema drift | 1 | Field-level diff against the baseline for each tool |
| Latency | 1 | Per-call and aggregated (p50/p95/p99) |
| LLM calls | 2 | Model, latency, finish reason — Anthropic, OpenAI, and Gemini |
| Token usage | 2 | Input + output + cache_read tokens per call |
| Context window | 2 | Tokens used vs model limit, utilisation %, per-trace growth rate |
| Context hogs | 2 | Per-tool average output size, % of context consumed |
| System prompt drift | 2 | SHA-256 per agent — alerts when prompt changes between calls |
| Trace context | 1–2 | Trace ID, session ID, agent ID — consistent across LLM + tool events |
| Failure patterns | 3 | Clustered failure analysis with natural-language descriptions and fix suggestions |
| Token optimization | 3 | Tools consuming >5% of context window, estimated token waste and cost savings |
| Quality scores | 3 | Per-tool reliability/schema-stability/latency-consistency grade (A–F) |
| Run quality | 3 | Per-trace context efficiency, failure recovery, tool diversity grade (A–F) |
| Multi-agent spans | 4 | W3C-compatible parent/child span linking across agent boundaries |
| Trace graphs | 4 | DAG reconstruction with topological order and cycle detection |
| Cross-agent attribution | 4 | Token usage and failure rate broken down per agent in a trace |
| Provider breakdown | 5 | LLM dashboard shows Anthropic / OpenAI / Google per model |

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

## Supported providers

| Provider | SDK | Intercepted endpoint |
|----------|-----|----------------------|
| Anthropic | `anthropic` | `api.anthropic.com/v1/messages` |
| OpenAI | `openai` | `api.openai.com/v1/chat/completions` |
| Google Gemini | `google-generativeai` | `generativelanguage.googleapis.com/.../generateContent` |

All three providers are auto-detected — no config required. Anjor reads the URL and routes to the right parser.

---

## What is NOT in v0.5

- `requests` library not intercepted (all three SDKs use httpx by default)
- No cloud sync, authentication, or team management
- Intelligence suggestions are heuristic — no LLM-powered explanations yet
- Streaming responses are not parsed (only non-streaming calls are captured)

---

## Releasing a new version

Tag the commit and push — the publish workflow runs CI first, then uploads to PyPI automatically:

```bash
git tag v0.5.0
git push origin v0.5.0
```

---

## Development

No Node/npm required — the dashboard is bundled static HTML served by the collector.

```bash
git clone https://github.com/anjor-labs/anjor.git
cd anjor
pip install -e ".[dev]"
pytest --cov=anjor --cov-fail-under=95 -q   # ≥95% coverage enforced
ruff check anjor/ tests/                     # zero lint errors
mypy anjor/                                  # strict type checking
anjor start                                  # collector + dashboard on :7843
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
