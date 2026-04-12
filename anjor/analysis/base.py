"""BaseAnalyser ABC — contract for all analysis components."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseAnalyser(ABC):
    """Abstract base for all Anjor analysers.

    Analysers are pure functions over event data — no I/O, no side effects.
    """

    @abstractmethod
    def analyse(self, data: Any) -> Any:
        """Run analysis and return results."""
        ...
