"""Post-session summarizer — calls Claude API with user's own key."""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class SessionSummary:
    session_id: str
    summary: str
    model: str


class SessionSummarizer:
    DEFAULT_MODEL = "claude-haiku-4-5-20251001"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.api_key = api_key
        self.model = model

    def summarize(
        self,
        session_id: str,
        messages: list[dict],  # type: ignore[type-arg]
        tool_call_count: int,
        tool_success_count: int,
        llm_call_count: int,
        estimated_cost_usd: float,
        models_used: list[str],
    ) -> SessionSummary:
        prompt = self._build_prompt(
            session_id,
            messages,
            tool_call_count,
            tool_success_count,
            llm_call_count,
            estimated_cost_usd,
            models_used,
        )
        text = self._call_api(prompt)
        return SessionSummary(session_id=session_id, summary=text, model=self.model)

    def _build_prompt(
        self,
        session_id: str,
        messages: list[dict],  # type: ignore[type-arg]
        tool_call_count: int,
        tool_success_count: int,
        llm_call_count: int,
        estimated_cost_usd: float,
        models_used: list[str],
    ) -> str:
        success_pct = int(tool_success_count / tool_call_count * 100) if tool_call_count else 0
        turns_preview = "\n".join(
            f"[{m['role']}] {m['content_preview'][:200]}" for m in messages[:8]
        )
        return (
            f"Summarize this AI coding session in 2-3 sentences. "
            f"Focus on what was accomplished and any notable issues.\n\n"
            f"Metrics: {tool_call_count} tool calls ({success_pct}% success), "
            f"{llm_call_count} LLM calls, ${estimated_cost_usd:.4f} estimated cost, "
            f"models: {', '.join(models_used) or 'unknown'}.\n\n"
            f"Conversation sample:\n{turns_preview or '(no messages captured)'}\n\n"
            f"Summary:"
        )

    def _call_api(self, prompt: str) -> str:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 300,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            return str(resp.json()["content"][0]["text"])
