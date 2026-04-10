"""FailureClassifier — priority-ordered rule chain for failure type classification."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agentscope.analysis.base import BaseAnalyser
from agentscope.core.events.tool_call import FailureType


class ClassificationContext:
    """Data available to classification rules."""

    def __init__(
        self,
        error_message: str = "",
        latency_ms: float = 0.0,
        timeout_threshold_ms: float = 5000.0,
        has_schema_drift: bool = False,
        status_code: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.error_message = error_message.lower()
        self.latency_ms = latency_ms
        self.timeout_threshold_ms = timeout_threshold_ms
        self.has_schema_drift = has_schema_drift
        self.status_code = status_code
        self.extra: dict[str, Any] = extra or {}


class BaseRule(ABC):
    """A single classification rule. Lower priority = evaluated first."""

    @property
    @abstractmethod
    def priority(self) -> int: ...

    @abstractmethod
    def matches(self, ctx: ClassificationContext) -> bool: ...

    @property
    @abstractmethod
    def failure_type(self) -> FailureType: ...


class TimeoutRule(BaseRule):
    """Classifies as TIMEOUT when latency exceeds threshold or error mentions timeout."""

    priority = 10

    def matches(self, ctx: ClassificationContext) -> bool:
        if ctx.latency_ms >= ctx.timeout_threshold_ms:
            return True
        timeout_keywords = ("timeout", "timed out", "deadline exceeded", "connection timed out")
        return any(kw in ctx.error_message for kw in timeout_keywords)

    @property
    def failure_type(self) -> FailureType:
        return FailureType.TIMEOUT


class SchemaDriftRule(BaseRule):
    """Classifies as SCHEMA_DRIFT when drift was detected."""

    priority = 20

    def matches(self, ctx: ClassificationContext) -> bool:
        return ctx.has_schema_drift

    @property
    def failure_type(self) -> FailureType:
        return FailureType.SCHEMA_DRIFT


class APIErrorRule(BaseRule):
    """Classifies as API_ERROR for HTTP 4xx/5xx or API error keywords."""

    priority = 30

    def matches(self, ctx: ClassificationContext) -> bool:
        if ctx.status_code is not None and ctx.status_code >= 400:
            return True
        api_error_keywords = (
            "api error",
            "http error",
            "status 4",
            "status 5",
            "rate limit",
            "unauthorized",
            "forbidden",
            "not found",
            "internal server error",
            "bad gateway",
            "service unavailable",
        )
        return any(kw in ctx.error_message for kw in api_error_keywords)

    @property
    def failure_type(self) -> FailureType:
        return FailureType.API_ERROR


class UnknownRule(BaseRule):
    """Catch-all — always matches."""

    priority = 999

    def matches(self, ctx: ClassificationContext) -> bool:
        return True

    @property
    def failure_type(self) -> FailureType:
        return FailureType.UNKNOWN


_DEFAULT_RULES: list[BaseRule] = [
    TimeoutRule(),
    SchemaDriftRule(),
    APIErrorRule(),
    UnknownRule(),
]


class FailureClassifier(BaseAnalyser):
    """Classifies failures using a priority-ordered rule chain.

    Rules are evaluated in ascending priority order. The first matching rule
    wins. Pass a custom rules list to override the defaults.
    """

    def __init__(self, rules: list[BaseRule] | None = None) -> None:
        self._rules = sorted(rules or _DEFAULT_RULES, key=lambda r: r.priority)

    def analyse(self, data: ClassificationContext) -> FailureType:
        """Classify the failure context and return a FailureType."""
        for rule in self._rules:
            if rule.matches(data):
                return rule.failure_type
        return FailureType.UNKNOWN  # pragma: no cover — UnknownRule always matches
