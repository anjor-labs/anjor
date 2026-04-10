"""BaseInterceptor ABC — contract for all HTTP interceptors."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseInterceptor(ABC):
    """Abstract base for all AgentScope interceptors."""

    @abstractmethod
    def install(self) -> None:
        """Install the interceptor (idempotent)."""
        ...

    @abstractmethod
    def uninstall(self) -> None:
        """Remove the interceptor (idempotent)."""
        ...

    @property
    @abstractmethod
    def is_installed(self) -> bool:
        """True if currently installed."""
        ...
