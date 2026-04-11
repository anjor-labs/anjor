"""Tests for the agentscope public API (patch, configure, get_pipeline)."""

from __future__ import annotations

import pytest

import agentscope
from agentscope.core.config import AgentScopeConfig
from agentscope.core.pipeline.pipeline import EventPipeline
from agentscope.interceptors.patch import PatchInterceptor
from agentscope.interceptors.proxy import ProxyInterceptor


class TestPublicAPI:
    def teardown_method(self) -> None:
        """Reset global state between tests."""
        agentscope._config = None
        agentscope._pipeline = None
        if agentscope._interceptor is not None:
            agentscope._interceptor.uninstall()
        agentscope._interceptor = None

    def test_patch_returns_interceptor(self) -> None:
        interceptor = agentscope.patch()
        assert isinstance(interceptor, PatchInterceptor)

    def test_patch_installs_interceptor(self) -> None:
        interceptor = agentscope.patch()
        assert interceptor.is_installed is True

    def test_patch_is_idempotent(self) -> None:
        i1 = agentscope.patch()
        i2 = agentscope.patch()
        assert i1 is i2  # same instance
        assert i2.is_installed is True

    def test_configure_defaults(self) -> None:
        cfg = agentscope.configure()
        assert isinstance(cfg, AgentScopeConfig)
        assert cfg.mode == "patch"

    def test_configure_with_kwargs(self) -> None:
        cfg = agentscope.configure(mode="proxy")
        assert cfg.mode == "proxy"

    def test_configure_with_config_instance(self) -> None:
        cfg = AgentScopeConfig(mode="proxy")  # type: ignore[call-arg]
        result = agentscope.configure(config=cfg)
        assert result is cfg

    def test_get_pipeline_returns_pipeline(self) -> None:
        pipeline = agentscope.get_pipeline()
        assert isinstance(pipeline, EventPipeline)

    def test_get_pipeline_is_singleton(self) -> None:
        p1 = agentscope.get_pipeline()
        p2 = agentscope.get_pipeline()
        assert p1 is p2

    def test_patch_uses_configured_pipeline(self) -> None:
        custom_pipeline = EventPipeline()
        interceptor = agentscope.patch(pipeline=custom_pipeline)
        assert interceptor._pipeline is custom_pipeline

    def test_patch_with_config(self) -> None:
        cfg = AgentScopeConfig(mode="patch")  # type: ignore[call-arg]
        interceptor = agentscope.patch(config=cfg)
        assert isinstance(interceptor, PatchInterceptor)
        assert agentscope._config is cfg

    def test_version_is_set(self) -> None:
        assert agentscope.__version__ == "0.2.0"

    def test_phase2_exports_available(self) -> None:
        from agentscope import ContextHogDetector, ContextWindowTracker, PromptDriftDetector

        assert ContextWindowTracker is not None
        assert ContextHogDetector is not None
        assert PromptDriftDetector is not None

    def test_all_exports_in_all(self) -> None:
        assert "ContextWindowTracker" in agentscope.__all__
        assert "ContextHogDetector" in agentscope.__all__
        assert "PromptDriftDetector" in agentscope.__all__


class TestProxyInterceptor:
    def test_proxy_interceptor_not_installed(self) -> None:
        proxy = ProxyInterceptor()
        assert proxy.is_installed is False

    def test_proxy_interceptor_install_raises(self) -> None:
        proxy = ProxyInterceptor()
        with pytest.raises(NotImplementedError, match="mitmproxy"):
            proxy.install()

    def test_proxy_interceptor_uninstall_noop(self) -> None:
        proxy = ProxyInterceptor()
        proxy.uninstall()  # must not raise
