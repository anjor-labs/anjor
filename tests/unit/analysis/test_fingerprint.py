"""Tests for schema fingerprinting — includes Hypothesis property-based tests."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agentscope.analysis.drift.fingerprint import diff_schemas, fingerprint


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------


@given(st.text(), st.integers())
def test_deterministic_with_text_and_int(name: str, count: int) -> None:
    """Same input always produces same hash."""
    payload = {"name": name, "count": count}
    assert fingerprint(payload) == fingerprint(payload)


@given(st.dictionaries(st.text(min_size=1), st.integers()))
def test_deterministic_with_dict(d: dict[str, int]) -> None:
    assert fingerprint(d) == fingerprint(d)


@given(st.dictionaries(st.text(min_size=1), st.integers()))
def test_key_order_invariant(d: dict[str, int]) -> None:
    """Reversing key order does not change hash."""
    reversed_d = dict(reversed(d.items()))
    assert fingerprint(d) == fingerprint(reversed_d)


@given(st.text(min_size=1))
def test_type_sensitive_int_vs_str(key: str) -> None:
    """Integer value and string value produce different hashes."""
    int_payload = {key: 1}
    str_payload = {key: "1"}
    assert fingerprint(int_payload) != fingerprint(str_payload)


@given(st.text(min_size=1))
def test_type_sensitive_bool_vs_int(key: str) -> None:
    """Bool and int produce different hashes (bool is subclass of int in Python)."""
    bool_payload = {key: True}
    int_payload = {key: 1}
    assert fingerprint(bool_payload) != fingerprint(int_payload)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestFingerprint:
    def test_returns_hex_string(self) -> None:
        result = fingerprint({"a": 1})
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex

    def test_empty_dict(self) -> None:
        result = fingerprint({})
        assert result  # non-empty hash

    def test_nested_dict(self) -> None:
        p1 = {"user": {"name": "alice", "age": 30}}
        p2 = {"user": {"name": "bob", "age": 99}}
        assert fingerprint(p1) == fingerprint(p2)  # values don't matter

    def test_list_value(self) -> None:
        p1 = {"items": [1, 2, 3]}
        p2 = {"items": [4, 5, 6]}
        assert fingerprint(p1) == fingerprint(p2)

    def test_empty_list_vs_nonempty_list(self) -> None:
        p1 = {"items": []}
        p2 = {"items": [1]}
        assert fingerprint(p1) != fingerprint(p2)

    def test_depth_limit(self) -> None:
        # Build a deeply nested dict (depth > 10)
        deep: dict = {}
        current = deep
        for _ in range(15):
            current["child"] = {}
            current = current["child"]
        # Should not raise — depth limit is handled gracefully
        result = fingerprint(deep)
        assert result

    def test_null_value(self) -> None:
        p1 = {"val": None}
        p2 = {"val": None}
        assert fingerprint(p1) == fingerprint(p2)

    def test_float_vs_int(self) -> None:
        p1 = {"x": 1.0}
        p2 = {"x": 1}
        assert fingerprint(p1) != fingerprint(p2)

    def test_different_structures_differ(self) -> None:
        p1 = {"a": 1, "b": 2}
        p2 = {"a": 1, "c": 2}
        assert fingerprint(p1) != fingerprint(p2)


class TestDiffSchemas:
    def test_identical_schemas(self) -> None:
        p = {"a": 1, "b": 2}
        result = diff_schemas(p, p)
        assert result["missing_fields"] == []
        assert result["unexpected_fields"] == []

    def test_missing_field(self) -> None:
        current = {"a": 1}
        reference = {"a": 1, "b": 2}
        result = diff_schemas(current, reference)
        assert "b" in result["missing_fields"]

    def test_unexpected_field(self) -> None:
        current = {"a": 1, "extra": "x"}
        reference = {"a": 1}
        result = diff_schemas(current, reference)
        assert "extra" in result["unexpected_fields"]

    def test_both_missing_and_unexpected(self) -> None:
        current = {"a": 1, "new": 2}
        reference = {"a": 1, "old": 2}
        result = diff_schemas(current, reference)
        assert "old" in result["missing_fields"]
        assert "new" in result["unexpected_fields"]

    def test_results_are_sorted(self) -> None:
        current = {}
        reference = {"z": 1, "a": 2, "m": 3}
        result = diff_schemas(current, reference)
        assert result["missing_fields"] == sorted(result["missing_fields"])
