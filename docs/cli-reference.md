# CLI Reference

All commands follow `anjor <subcommand> [options]`. Run `anjor <subcommand> --help` for full flag details.

---

## `anjor start`

Start the collector, dashboard, and optionally the transcript watcher in a single process.

```bash
anjor start                                          # collector + dashboard only
anjor start --watch-transcripts                      # + transcript watcher (auto-detect)
anjor start --watch-transcripts --providers claude   # Claude Code only
anjor start --watch-transcripts --project myapp      # tag all events with project
anjor start --port 8000                              # custom port (default: 7843)
anjor start --no-capture-messages                    # disable message capture
```

Dashboard opens at `http://localhost:<port>/ui/`.

---

## `anjor mcp`

Start the collector as an MCP server (stdio). Used via `.mcp.json` so Claude Code or Gemini CLI auto-starts it.

```bash
anjor mcp --watch-transcripts
anjor mcp --watch-transcripts --providers gemini
anjor mcp --no-capture-messages
```

The MCP server exposes one tool: `anjor_status`. Claude Code calls it mid-session to get a time-windowed health summary with actionable insights.

---

## `anjor watch-transcripts`

Watch transcript files without starting the HTTP collector. Useful if the collector is already running separately.

```bash
anjor watch-transcripts                              # auto-detect providers
anjor watch-transcripts --providers claude,gemini    # specific providers
anjor watch-transcripts --list-providers             # show detected agents
anjor watch-transcripts --poll-interval 5.0          # custom poll interval (seconds)
```

---

## `anjor status`

Print a compact health summary from the running collector. Exits 0 if healthy, 2 if collector is unreachable.

```bash
anjor status                          # last 2h
anjor status --since-minutes 30       # last 30 minutes
anjor status --project myapp          # filtered to project
anjor status --port 8000              # custom collector port
```

Example output:
```
last 2h: 47 calls · 6% failure · $0.08 · 74% ctx
⚠  web_search has a 30% failure rate (3/10 calls)
⚠  Context at 74%
```

Silent (no output, exit 0) when everything is healthy.

---

## `anjor report`

Generate a quality report from SQLite — no running collector needed.

```bash
anjor report                                         # last 2h, text output
anjor report --session last                          # scope to most recent session
anjor report --since 24h                             # last 24 hours
anjor report --format json                           # JSON output
anjor report --format markdown                       # Markdown (good for CI artifacts)
anjor report --project myapp                         # filter by project
anjor report --assert "success_rate >= 0.95"         # exit 1 if assertion fails
anjor report --assert "p95_latency_ms <= 3000" \
             --assert "failure_count < 5"
anjor report --db /path/to/custom.db
```

**Supported assertion metrics:** `success_rate`, `p95_latency_ms`, `failure_count`, `total_cost_usd`

**Since formats:** `30m`, `2h`, `24h`, `7d`

---

## `anjor diff`

Compare current vs prior time window to detect regressions.

```bash
anjor diff --window 24h                              # last 24h vs prior 24h
anjor diff --window 7d                               # last 7d vs prior 7d
anjor diff --format json                             # JSON output
anjor diff --project myapp

# Named baselines — save a snapshot, compare later
anjor diff --window 24h --save-baseline before-deploy
# ... after deploy ...
anjor diff --window 24h --vs before-deploy
```

Output shows per-tool changes in success rate, p95 latency, and failure count, with `↑` (improvement) / `↓` (regression) / `=` (unchanged) indicators.

---

## `anjor summarize`

Generate a natural-language summary of a session using Claude (requires your own API key).

```bash
anjor summarize                                      # most recent session
anjor summarize --session last
anjor summarize --session <session-id>
anjor summarize --api-key sk-ant-...                 # or set ANTHROPIC_API_KEY
anjor summarize --model claude-haiku-4-5-20251001    # default model
anjor summarize --save                               # persist summary to DB (shows in Replay)
anjor summarize --db /path/to/custom.db
```

The summary uses local session data (messages, tool call stats, cost) — no agent data is sent to Anthropic except what you explicitly pass to your API key. Summaries stored in DB appear as a banner at the top of Session Replay.
