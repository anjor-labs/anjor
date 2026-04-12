"""ParserRegistry — URL-pattern matching, priority-ordered parser selection."""

from __future__ import annotations

from typing import Any

from anjor.core.events.base import BaseEvent
from anjor.interceptors.parsers.base import BaseParser


class ParserRegistry:
    """Registry of parsers, matched by URL in registration order.

    Parsers are tried in the order they were registered. The first parser
    whose can_parse() returns True handles the request.
    """

    def __init__(self) -> None:
        self._parsers: list[BaseParser] = []

    def register(self, parser: BaseParser) -> None:
        """Register a parser. Later registrations are checked later."""
        self._parsers.append(parser)

    def find_parser(self, url: str) -> BaseParser | None:
        """Return the first parser that can handle this URL, or None."""
        for parser in self._parsers:
            if parser.can_parse(url):
                return parser
        return None

    def parse(
        self,
        url: str,
        request_body: dict[str, Any],
        response_body: dict[str, Any],
        latency_ms: float,
        status_code: int,
    ) -> list[BaseEvent]:
        """Find a matching parser and extract events. Returns [] if no match."""
        parser = self.find_parser(url)
        if parser is None:
            return []
        return parser.parse(url, request_body, response_body, latency_ms, status_code)


def build_default_registry() -> ParserRegistry:
    """Build the default registry with all supported parsers."""
    from anjor.interceptors.parsers.anthropic import AnthropicParser
    from anjor.interceptors.parsers.gemini import GeminiParser
    from anjor.interceptors.parsers.openai import OpenAIParser

    registry = ParserRegistry()
    registry.register(AnthropicParser())
    registry.register(OpenAIParser())
    registry.register(GeminiParser())
    return registry
