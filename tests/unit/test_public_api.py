"""Tests for the anjor public API (patch, configure, get_pipeline)."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch as mock_patch

import pytest

import anjor
from anjor.core.config import AnjorConfig
from anjor.core.pipeline.pipeline import EventPipeline
from anjor.interceptors.patch import PatchInterceptor
from anjor.interceptors.proxy import ProxyInterceptor


def _reset_anjor_globals() -> None:
    """Reset all module-level singletons between tests."""
    anjor._config = None
    anjor._pipeline = None
    if anjor._interceptor is not None:
        anjor._interceptor.uninstall()
    anjor._interceptor = None
    if anjor._requests_interceptor is not None:
        anjor._requests_interceptor.uninstall()
    anjor._requests_interceptor = None
    # Background loop/thread are daemon threads — leave them running to avoid
    # race conditions on teardown, but clear the module refs so the next test
    # that calls patch() re-evaluates whether a live loop exists.
    if anjor._bg_loop is not None and not anjor._bg_loop.is_running():
        anjor._bg_loop = None
        anjor._bg_thread = None


class TestPublicAPI:
    def teardown_method(self) -> None:
        _reset_anjor_globals()

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
        assert isinstance(anjor.__version__, str)
        assert anjor.__version__ != ""

    def test_phase2_exports_available(self) -> None:
        from anjor import ContextHogDetector, ContextWindowTracker, PromptDriftDetector

        assert ContextWindowTracker is not None
        assert ContextHogDetector is not None
        assert PromptDriftDetector is not None

    def test_all_exports_in_all(self) -> None:
        assert "ContextWindowTracker" in anjor.__all__
        assert "ContextHogDetector" in anjor.__all__
        assert "PromptDriftDetector" in anjor.__all__


class TestAutoStart:
    def teardown_method(self) -> None:
        _reset_anjor_globals()

    def test_auto_start_disabled_skips_health_check(self) -> None:
        with mock_patch("anjor._collector_running") as mock_check:
            anjor.patch(auto_start=False)
            mock_check.assert_not_called()

    def test_auto_start_already_running_no_subprocess(self) -> None:
        with mock_patch("anjor._collector_running", return_value=True) as mock_check:
            with mock_patch("anjor._start_collector_subprocess") as mock_start:
                anjor.patch(auto_start=True)
                mock_check.assert_called_once()
                mock_start.assert_not_called()

    def test_auto_start_not_running_starts_subprocess(self) -> None:
        with mock_patch("anjor._collector_running", return_value=False):
            with mock_patch("anjor._start_collector_subprocess") as mock_start:
                anjor.patch(auto_start=True)
                mock_start.assert_called_once()

    def test_auto_start_idempotent_on_second_patch_call(self) -> None:
        with mock_patch("anjor._collector_running", return_value=False):
            with mock_patch("anjor._start_collector_subprocess") as mock_start:
                anjor.patch(auto_start=True)
                anjor.patch(auto_start=True)  # second call — interceptor already set
                mock_start.assert_called_once()  # subprocess started only once

    def test_collector_running_returns_true_on_200(self) -> None:
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        with mock_patch("urllib.request.urlopen", return_value=mock_resp):
            with mock_patch("time.sleep"):
                result = anjor._collector_running("127.0.0.1", 7843)
        assert result is True

    def test_collector_running_returns_false_on_connection_error(self) -> None:
        with mock_patch("urllib.request.urlopen", side_effect=OSError("refused")):
            with mock_patch("time.sleep"):
                result = anjor._collector_running("127.0.0.1", 7843)
        assert result is False

    def test_start_collector_subprocess_prints_to_stderr(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_popen = MagicMock()
        with mock_patch("subprocess.Popen", return_value=mock_popen) as popen_mock:
            anjor._start_collector_subprocess("127.0.0.1", 7843)
        captured = capsys.readouterr()
        assert "anjor: collector started on http://localhost:7843/ui/" in captured.err
        popen_mock.assert_called_once()

    def test_start_collector_subprocess_uses_start_new_session(self) -> None:
        with mock_patch("subprocess.Popen") as popen_mock:
            anjor._start_collector_subprocess("127.0.0.1", 7843)
        _, kwargs = popen_mock.call_args
        assert kwargs.get("start_new_session") is True

    def test_start_collector_subprocess_custom_host(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with mock_patch("subprocess.Popen"):
            anjor._start_collector_subprocess("0.0.0.0", 9000)  # noqa: S104
        captured = capsys.readouterr()
        assert "http://0.0.0.0:9000/ui/" in captured.err


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
