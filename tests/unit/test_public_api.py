"""Tests for the anjor public API (patch, configure, get_pipeline)."""

from __future__ import annotations

import pytest

import anjor
from anjor.core.config import AnjorConfig
from anjor.core.pipeline.pipeline import EventPipeline
from anjor.interceptors.patch import PatchInterceptor
from anjor.interceptors.proxy import ProxyInterceptor


class TestPublicAPI:
    def teardown_method(self) -> None:
        """Reset global state between tests."""
        anjor._config = None
        anjor._pipeline = None
        if anjor._interceptor is not None:
            anjor._interceptor.uninstall()
        anjor._interceptor = None

    def test_patch_returns_interceptor(self) -> None:
        interceptor = anjor.patch()
        assert isinstance(interceptor, PatchInterceptor)

    def test_patch_installs_interceptor(self) -> None:
        interceptor = anjor.patch()
        assert interceptor.is_installed is True

    def test_patch_is_idempotent(self) -> None:
        i1 = anjor.patch()
        i2 = anjor.patch()
        assert i1 is i2  # same instance
        assert i2.is_installed is True

    def test_configure_defaults(self) -> None:
        cfg = anjor.configure()
        assert isinstance(cfg, AnjorConfig)
        assert cfg.mode == "patch"

    def test_configure_with_kwargs(self) -> None:
        cfg = anjor.configure(mode="proxy")
        assert cfg.mode == "proxy"

    def test_configure_with_config_instance(self) -> None:
        cfg = AnjorConfig(mode="proxy")  # type: ignore[call-arg]
        result = anjor.configure(config=cfg)
        assert result is cfg

    def test_get_pipeline_returns_pipeline(self) -> None:
        pipeline = anjor.get_pipeline()
        assert isinstance(pipeline, EventPipeline)

    def test_get_pipeline_is_singleton(self) -> None:
        p1 = anjor.get_pipeline()
        p2 = anjor.get_pipeline()
        assert p1 is p2

    def test_patch_uses_configured_pipeline(self) -> None:
        custom_pipeline = EventPipeline()
        interceptor = anjor.patch(pipeline=custom_pipeline)
        assert interceptor._pipeline is custom_pipeline

    def test_patch_with_config(self) -> None:
        cfg = AnjorConfig(mode="patch")  # type: ignore[call-arg]
        interceptor = anjor.patch(config=cfg)
        assert isinstance(interceptor, PatchInterceptor)
        assert anjor._config is cfg

    def test_version_is_set(self) -> None:
        assert anjor.__version__ == "0.3.0"

    def test_phase2_exports_available(self) -> None:
        from anjor import ContextHogDetector, ContextWindowTracker, PromptDriftDetector

        assert ContextWindowTracker is not None
        assert ContextHogDetector is not None
        assert PromptDriftDetector is not None

    def test_all_exports_in_all(self) -> None:
        assert "ContextWindowTracker" in anjor.__all__
        assert "ContextHogDetector" in anjor.__all__
        assert "PromptDriftDetector" in anjor.__all__


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
