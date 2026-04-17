-- Migration 005: add source column to tool_calls and llm_calls.
-- Identifies how anjor learned about this event:
--   '' (empty)       = httpx interceptor (anjor.patch() — default for existing rows)
--   'mcp'            = captured via anjor MCP server
--   'claude_code'    = Claude Code transcript watcher
--   'gemini_cli'     = Gemini CLI transcript watcher
--
-- ALTER TABLE ... ADD COLUMN with DEFAULT '' is supported by SQLite >= 3.37.0.
-- All macOS/Linux systems shipping Python 3.11+ satisfy this requirement.

ALTER TABLE tool_calls ADD COLUMN source TEXT NOT NULL DEFAULT '';
ALTER TABLE llm_calls  ADD COLUMN source TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_tool_calls_source ON tool_calls (source);
CREATE INDEX IF NOT EXISTS idx_llm_calls_source  ON llm_calls  (source);
