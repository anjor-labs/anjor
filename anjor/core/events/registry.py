"""EventTypeRegistry — maps EventType strings to event classes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from anjor.core.events.base import EventType

if TYPE_CHECKING:
    from anjor.core.events.base import BaseEvent


class EventTypeRegistry:
    """Central registry mapping EventType → BaseEvent subclass.

    - register: add a mapping (raises on duplicate unless replace=True)
    - get: retrieve class (raises clearly on unknown type)
    - replace: overwrite an existing mapping
    """

    def __init__(self) -> None:
        self._registry: dict[EventType, type[BaseEvent]] = {}

    def register(self, event_type: EventType, cls: type[BaseEvent]) -> None:
        """Register an event class. Raises ValueError on duplicate."""
        if event_type in self._registry:
            raise ValueError(
                f"EventType {event_type!r} is already registered as "
                f"{self._registry[event_type].__name__}. "
                "Use replace() to overwrite intentionally."
            )
        self._registry[event_type] = cls

    def replace(self, event_type: EventType, cls: type[BaseEvent]) -> None:
        """Overwrite an existing registration."""
        self._registry[event_type] = cls

    def get(self, event_type: EventType) -> type[BaseEvent]:
        """Retrieve an event class. Raises KeyError on unknown type."""
        if event_type not in self._registry:
            registered = list(self._registry.keys())
            raise KeyError(f"Unknown EventType {event_type!r}. Registered types: {registered}")
        return self._registry[event_type]

    def all(self) -> dict[EventType, type[BaseEvent]]:
        """Return a snapshot of the full registry."""
        return dict(self._registry)


def _build_default_registry() -> EventTypeRegistry:
    """Build the registry pre-populated with all known event types."""
    from anjor.core.events.agent_span import AgentSpanEvent
    from anjor.core.events.llm_call import LLMCallEvent
    from anjor.core.events.tool_call import ToolCallEvent

    reg = EventTypeRegistry()
    reg.register(EventType.TOOL_CALL, ToolCallEvent)
    reg.register(EventType.LLM_CALL, LLMCallEvent)
    reg.register(EventType.AGENT_SPAN, AgentSpanEvent)
    return reg


default_registry: EventTypeRegistry = _build_default_registry()
