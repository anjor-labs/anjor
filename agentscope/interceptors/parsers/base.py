"""BaseParser ABC — contract for HTTP request/response parsers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentscope.core.events.base import BaseEvent


class BaseParser(ABC):
    """Parses an HTTP request/response pair into a list of AgentScope events."""

    @abstractmethod
    def can_parse(self, url: str) -> bool:
        """Return True if this parser handles the given URL."""
        ...

    @abstractmethod
    def parse(
        self,
        url: str,
        request_body: dict[str, Any],
        response_body: dict[str, Any],
        latency_ms: float,
        status_code: int,
    ) -> list[BaseEvent]:
        """Extract events from the request/response pair.

        Args:
            url: The request URL.
            request_body: Parsed JSON request body.
            response_body: Parsed JSON response body.
            latency_ms: Request latency in milliseconds.
            status_code: HTTP response status code.

        Returns:
            A list of events (may be empty if nothing to extract).
        """
        ...
