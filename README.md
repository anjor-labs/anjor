# AgentScope

Observability for AI agents. One-line install. No cloud. No account required.

AgentScope intercepts your agent's HTTP traffic at the protocol layer and gives you full visibility into every tool call — latency, schema drift, failures, token usage — without changing how you build.

## Install

```bash
pip install agentscope
```

## Quickstart

```python
import agentscope
agentscope.patch()  # that's it — httpx is now instrumented

import anthropic
client = anthropic.Anthropic()
# make tool calls as normal — they're captured automatically
```

Start the local collector (stores events to SQLite):

```bash
python scripts/start_collector.py
```

Query your tool call data:

```bash
curl http://localhost:7843/health
curl http://localhost:7843/tools
curl http://localhost:7843/tools/web_search
```

## What it captures (Phase 1)

- Tool name, status (success/failure), failure type
- Latency per tool call
- Input/output schema fingerprints
- Schema drift detection (field-level diff against baseline)
- Token usage per call
- Trace and session IDs

## What it does NOT do (yet)

- No LLM call tracing (Phase 2)
- No context window intelligence (Phase 2)
- No optimization suggestions (Phase 3)
- No multi-agent tracing (Phase 4)
- No cloud sync
- No authentication or team management
- No dashboard UI (API-only in Phase 1)

## Local only

API keys, prompts, and payloads never leave your machine. The collector runs locally. Zero cloud dependency.

## Development

```bash
bash scripts/dev_setup.sh   # one-command setup
pytest                      # run tests (≥95% coverage enforced)
ruff check .                # lint
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full layer diagram and design decisions.
