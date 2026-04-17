-- Migration 006: add project column to tool_calls and llm_calls
ALTER TABLE tool_calls ADD COLUMN project TEXT NOT NULL DEFAULT '';
ALTER TABLE llm_calls ADD COLUMN project TEXT NOT NULL DEFAULT '';
