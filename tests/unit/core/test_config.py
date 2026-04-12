"""Unit tests for AnjorConfig."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from anjor.core.config import AnjorConfig, SanitiseConfig


class TestAnjorConfig:
    def test_default_values(self) -> None:
        cfg = AnjorConfig()
        assert cfg.mode == "patch"
        assert cfg.proxy_port == 7842
        assert cfg.collector_port == 7843
        assert cfg.db_path == "anjor.db"
        assert cfg.log_level == "INFO"
        assert cfg.max_payload_size_kb == 512
        assert cfg.batch_size == 100
        assert cfg.batch_interval_ms == 500

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANJOR_MODE", "proxy")
        monkeypatch.setenv("ANJOR_COLLECTOR_PORT", "9000")
        cfg = AnjorConfig()
        assert cfg.mode == "proxy"
        assert cfg.collector_port == 9000

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(Exception, match="mode"):
            AnjorConfig(mode="invalid")  # type: ignore[call-arg]

    def test_invalid_log_level_raises(self) -> None:
        with pytest.raises(ValidationError):
            AnjorConfig(log_level="VERBOSE")  # type: ignore[call-arg]

    def test_proxy_port_bounds(self) -> None:
        with pytest.raises(ValidationError):
            AnjorConfig(proxy_port=0)  # type: ignore[call-arg]
        with pytest.raises(ValidationError):
            AnjorConfig(proxy_port=70000)  # type: ignore[call-arg]

    def test_batch_size_min(self) -> None:
        with pytest.raises(ValidationError):
            AnjorConfig(batch_size=0)  # type: ignore[call-arg]

    def test_frozen_prevents_mutation(self) -> None:
        cfg = AnjorConfig()
        with pytest.raises(ValidationError):
            cfg.mode = "proxy"  # type: ignore[misc]

    def test_valid_modes(self) -> None:
        for mode in ("patch", "proxy"):
            cfg = AnjorConfig(mode=mode)  # type: ignore[call-arg]
            assert cfg.mode == mode

    def test_valid_log_levels(self) -> None:
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            cfg = AnjorConfig(log_level=level)  # type: ignore[call-arg]
            assert cfg.log_level == level

    def test_sanitise_config_nested(self) -> None:
        cfg = AnjorConfig()
        assert isinstance(cfg.sanitise, SanitiseConfig)
        assert "*api_key*" in cfg.sanitise.strip_patterns
        assert "*secret*" in cfg.sanitise.strip_patterns


class TestSanitiseConfig:
    def test_default_patterns(self) -> None:
        cfg = SanitiseConfig()
        expected = ["*api_key*", "*secret*", "*password*", "*token*", "*auth*", "*bearer*"]
        for pattern in expected:
            assert pattern in cfg.strip_patterns

    def test_frozen(self) -> None:
        cfg = SanitiseConfig()
        with pytest.raises(ValidationError):
            cfg.strip_patterns = []  # type: ignore[misc]
