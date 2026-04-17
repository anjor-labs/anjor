# Providers & Transcript Watchers

## LLM SDK interception (`anjor.patch()`)

`anjor.patch()` monkey-patches `httpx.Client` and `httpx.AsyncClient`. Any Python library that uses httpx under the hood is automatically captured — no per-library configuration needed.

| Provider | Python SDK | Intercepted URL |
|----------|-----------|----------------|
| Anthropic | `anthropic` | `api.anthropic.com/v1/messages` |
| OpenAI | `openai` | `api.openai.com/v1/chat/completions` |
| Google Gemini | `google-generativeai` | `generativelanguage.googleapis.com/.../generateContent` |

All three are auto-detected. If you use a different provider that goes through httpx, it will also be captured (as an unrecognised provider).

### Streaming

Streaming responses are captured only when the stream is fully consumed. If your code exits before reading all chunks (partial streaming), that call is not recorded.

### Requests library

```python
import anjor
anjor.patch_requests()   # patches requests.Session in addition to httpx
```

---

## AI coding agent watchers

Anjor watches transcript files written by AI coding agents. No code changes needed in those agents — Anjor reads the files they already write.

| Agent | Source tag | Transcript path | MCP support | Message capture |
|-------|-----------|----------------|-------------|-----------------|
| **Claude Code** | `claude_code` | `~/.claude/projects/**/*.jsonl` | Yes | Yes |
| **Gemini CLI** | `gemini_cli` | `~/.gemini/tmp/**/*.json` | Yes | Yes |
| **OpenAI Codex** | `openai_codex` | `~/.codex/sessions/**/*.jsonl` | Coming soon | Yes |

### Starting watchers

```bash
anjor start --watch-transcripts                      # auto-detect all agents
anjor start --watch-transcripts --providers claude   # Claude Code only
anjor start --watch-transcripts --providers claude,gemini
anjor watch-transcripts --list-providers             # show detected agents
```

### Session Replay

When `capture_messages = true` (the default), user messages and assistant responses are captured as `MessageEvent` (first 500 chars per turn). These appear in Session Replay at `/ui/replay.html`.

To disable:
```toml
# .anjor.toml
capture_messages = false
```

### Watcher offsets

Anjor tracks read progress per file in `~/.anjor/watcher_offsets.json`. To force re-processing all history:
```bash
rm ~/.anjor/watcher_offsets.json
```

### MCP integration for Claude Code

Add to `.mcp.json` in your project root:
```json
{
  "mcpServers": {
    "anjor": {
      "command": "anjor",
      "args": ["mcp", "--watch-transcripts"]
    }
  }
}
```

This auto-starts the collector with Claude Code and adds `anjor_status` as a tool. Claude can call it mid-session to get a health summary — failure rates, context pressure, estimated cost. Returns nothing when everything is healthy.

### MCP integration for Gemini CLI

Add to `.gemini/settings.json` (or `~/.gemini/settings.json` for global):
```json
{
  "mcpServers": {
    "anjor": {
      "command": "anjor",
      "args": ["mcp", "--watch-transcripts", "--providers", "gemini"]
    }
  }
}
```
