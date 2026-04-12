"""OpenAIParser — Phase 2 stub. Not implemented."""

from __future__ import annotations

from typing import Any

from anjor.core.events.base import BaseEvent
from anjor.interceptors.parsers.base import BaseParser


class OpenAIParser(BaseParser):
    """Stub for Phase 2 OpenAI API parsing. Do not implement until Phase 2."""

    def can_parse(self, url: str) -> bool:
        return "api.openai.com" in url

    def parse(
        self,
        url: str,
        request_body: dict[str, Any],
        response_body: dict[str, Any],
        latency_ms: float,
        status_code: int,
    ) -> list[BaseEvent]:
        # Phase 2: implement OpenAI tool call extraction
        return []
