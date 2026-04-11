# AgentScope

[![CI](https://github.com/anji/agentscope/actions/workflows/ci.yml/badge.svg)](https://github.com/anji/agentscope/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-97%25-brightgreen)](https://github.com/anji/agentscope)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Observability for AI agents. One-line install. No cloud. No account required.

AgentScope intercepts your agent's HTTP traffic at the protocol layer and gives you full visibility into every LLM call and tool use — latency, token usage, context window growth, schema drift, prompt changes — without changing how you build.

---

## Install

```bash
pip install agentscope
```

---

## Quickstart

**1. Start the local collector** (stores events to SQLite):

```bash
python scripts/start_collector.py
```

**2. Add one line to your agent:**

```python
import agentscope
agentscope.patch()   # that's it — httpx is now instrumented

import anthropic
client = anthropic.Anthropic()
# make tool calls as normal — they're captured automatically
```

**3. Query your data:**

```bash
curl http://localhost:7843/health
curl http://localhost:7843/tools
curl http://localhost:7843/tools/web_search
```

No API key? Use [`respx`](https://lundberg.github.io/respx/) to replay a mock response — see the [quickstart guide](docs/quickstart.md).

---

## What it captures

| Signal | Details |
|--------|---------|
| LLM calls | Model, latency, finish reason — for every Anthropic `/v1/messages` call |
| Tool calls | Name, status (success/failure), failure type |
| Token usage | Input + output + cache_read tokens per call |
| Context window | Tokens used vs model limit, utilisation %, per-trace growth rate |
| Context hogs | Per-tool average output size, % of context consumed |
| System prompt drift | SHA-256 per agent — alerts when prompt changes between calls |
| Schema fingerprints | SHA-256 structural hash of tool input/output shape |
| Schema drift | Field-level diff against the baseline for each tool |
| Trace context | Trace ID, session ID, agent ID — consistent across LLM + tool events |
| Latency | Per-call and aggregated (p50/p95/p99) |

---

## Configuration

Via environment variables:

```bash
AGENTSCOPE_DB_PATH=./my_project.db python my_agent.py
AGENTSCOPE_BATCH_SIZE=1 AGENTSCOPE_BATCH_INTERVAL_MS=100 python my_agent.py
AGENTSCOPE_LOG_LEVEL=DEBUG python my_agent.py
```

Via `.agentscope.toml` in your project root:

```toml
db_path = "my_project.db"
batch_size = 10
batch_interval_ms = 200
log_level = "DEBUG"
```

Via code:

```python
import agentscope
from agentscope.core.config import AgentScopeConfig

agentscope.patch(config=AgentScopeConfig(db_path="my_project.db", batch_size=1))
```

---

## What is NOT in v0.2

- No optimisation suggestions (Phase 3)
- No multi-agent tracing (Phase 4)
- No dashboard UI — API and SQLite only
- No cloud sync, authentication, or team management
- `requests` library not intercepted (Anthropic SDK uses httpx by default)
- OpenAI parser not implemented (stub only)

---

## Development

```bash
git clone https://github.com/anji/agentscope.git
cd agentscope
bash scripts/dev_setup.sh   # creates .venv, installs deps
source .venv/bin/activate
.venv/bin/pytest            # ≥95% coverage enforced
ruff check .                # zero lint errors
mypy agentscope/            # strict type checking
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidelines.

---

## Documentation

- [Quickstart — see it in action](docs/quickstart.md)
- [Architecture — layer diagram and design decisions](docs/architecture.md)
- [Code flow — execution traces end-to-end](docs/code_flow.md)

---

## License

[MIT](LICENSE) © Anjani Kumar
