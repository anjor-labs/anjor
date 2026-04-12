"""DriftDetector — compares payload schema against baseline, emits SchemaDrift."""

from __future__ import annotations

from typing import Any

from anjor.analysis.base import BaseAnalyser
from anjor.analysis.drift.fingerprint import diff_schemas, fingerprint
from anjor.core.events.tool_call import SchemaDrift


class DriftDetector(BaseAnalyser):
    """Detects schema drift for a named tool.

    First call for a tool stores the baseline. Subsequent calls compare
    the current payload against the baseline and return a SchemaDrift.
    """

    def __init__(self) -> None:
        # tool_name → {"payload": dict, "hash": str}
        self._baselines: dict[str, dict[str, Any]] = {}

    def analyse(self, data: Any) -> SchemaDrift | None:
        """Not used directly — call check() instead."""
        raise NotImplementedError("Use check(tool_name, payload) directly.")

    def check(
        self, tool_name: str, payload: dict[str, Any]
    ) -> SchemaDrift | None:
        """Check payload against baseline for tool_name.

        - If no baseline exists: stores this as baseline and returns None.
        - If baseline exists: computes diff and returns SchemaDrift.
        """
        current_hash = fingerprint(payload)

        if tool_name not in self._baselines:
            self._baselines[tool_name] = {
                "payload": payload,
                "hash": current_hash,
            }
            return None

        baseline = self._baselines[tool_name]
        expected_hash = baseline["hash"]

        if current_hash == expected_hash:
            return SchemaDrift(
                detected=False,
                missing_fields=[],
                unexpected_fields=[],
                expected_hash=expected_hash,
            )

        diff = diff_schemas(payload, baseline["payload"])
        return SchemaDrift(
            detected=True,
            missing_fields=diff["missing_fields"],
            unexpected_fields=diff["unexpected_fields"],
            expected_hash=expected_hash,
        )

    def reset(self, tool_name: str | None = None) -> None:
        """Clear baseline(s). Pass tool_name to reset one, None to reset all."""
        if tool_name is None:
            self._baselines.clear()
        else:
            self._baselines.pop(tool_name, None)
