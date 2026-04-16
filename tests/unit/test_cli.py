"""Tests for the anjor CLI entry point."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from anjor.cli import _check_port, main


class TestCLI:
    def test_no_args_exits_zero(self) -> None:
        with patch.object(sys, "argv", ["anjor"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 0

    def test_start_calls_uvicorn(self) -> None:
        mock_run = MagicMock()
        with (
            patch.object(sys, "argv", ["anjor", "start"]),
            patch("anjor.cli._check_port", return_value="free"),
            patch("uvicorn.run", mock_run),
            patch("builtins.print"),
        ):
            main()
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 7843

    def test_start_custom_port(self) -> None:
        mock_run = MagicMock()
        with (
            patch.object(sys, "argv", ["anjor", "start", "--port", "9000"]),
            patch("anjor.cli._check_port", return_value="free"),
            patch("uvicorn.run", mock_run),
            patch("builtins.print"),
        ):
            main()
        _, kwargs = mock_run.call_args
        assert kwargs["port"] == 9000

    def test_start_custom_db(self) -> None:
        mock_run = MagicMock()
        with (
            patch.object(sys, "argv", ["anjor", "start", "--db", "custom.db"]),
            patch("anjor.cli._check_port", return_value="free"),
            patch("uvicorn.run", mock_run),
            patch("builtins.print"),
        ):
            main()
        mock_run.assert_called_once()

    def test_start_prints_urls(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_run = MagicMock()
        with (
            patch.object(sys, "argv", ["anjor", "start"]),
            patch("anjor.cli._check_port", return_value="free"),
            patch("uvicorn.run", mock_run),
        ):
            main()
        out = capsys.readouterr().out
        assert "7843" in out
        assert "dashboard" in out.lower() or "/ui/" in out

    def test_start_watch_transcripts_starts_watcher(self) -> None:
        mock_run = MagicMock()
        mock_manager_start = MagicMock()
        with (
            patch.object(
                sys, "argv", ["anjor", "start", "--watch-transcripts", "--providers", "claude"]
            ),
            patch("anjor.cli._check_port", return_value="free"),
            patch("uvicorn.run", mock_run),
            patch("anjor.watchers.manager.WatcherManager.start", mock_manager_start),
            patch(
                "anjor.watchers.manager.WatcherManager.active_providers",
                return_value=["claude_code"],
            ),
            patch("builtins.print"),
        ):
            main()
        mock_manager_start.assert_called_once_with(["claude"])
        mock_run.assert_called_once()

    def test_start_no_watch_transcripts_skips_watcher(self) -> None:
        mock_run = MagicMock()
        mock_manager_cls = MagicMock()
        with (
            patch.object(sys, "argv", ["anjor", "start"]),
            patch("anjor.cli._check_port", return_value="free"),
            patch("uvicorn.run", mock_run),
            patch("anjor.watchers.manager.WatcherManager", mock_manager_cls),
            patch("builtins.print"),
        ):
            main()
        mock_manager_cls.assert_not_called()


# ---------------------------------------------------------------------------
# Port-collision handling
# ---------------------------------------------------------------------------


class TestPortCollision:
    def test_anjor_already_running_exits_zero(self) -> None:
        """When an anjor collector is already on the port, exit 0 (not an error)."""
        with (
            patch.object(sys, "argv", ["anjor", "start"]),
            patch("anjor.cli._check_port", return_value="anjor"),
            patch("builtins.print"),
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 0

    def test_anjor_already_running_prints_url(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch.object(sys, "argv", ["anjor", "start"]),
            patch("anjor.cli._check_port", return_value="anjor"),
        ):
            with pytest.raises(SystemExit):
                main()
        out = capsys.readouterr().out
        assert "already running" in out
        assert "7843" in out
        assert "/ui/" in out

    def test_anjor_already_running_does_not_call_uvicorn(self) -> None:
        mock_run = MagicMock()
        with (
            patch.object(sys, "argv", ["anjor", "start"]),
            patch("anjor.cli._check_port", return_value="anjor"),
            patch("uvicorn.run", mock_run),
            patch("builtins.print"),
        ):
            with pytest.raises(SystemExit):
                main()
        mock_run.assert_not_called()

    def test_other_process_on_port_exits_one(self) -> None:
        """When another (non-anjor) process owns the port, exit 1."""
        with (
            patch.object(sys, "argv", ["anjor", "start"]),
            patch("anjor.cli._check_port", return_value="other"),
            patch("builtins.print"),
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1

    def test_other_process_on_port_prints_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch.object(sys, "argv", ["anjor", "start"]),
            patch("anjor.cli._check_port", return_value="other"),
        ):
            with pytest.raises(SystemExit):
                main()
        out = capsys.readouterr().out
        assert "7843" in out
        assert "already in use" in out

    def test_other_process_suggests_next_port(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch.object(sys, "argv", ["anjor", "start"]),
            patch("anjor.cli._check_port", return_value="other"),
        ):
            with pytest.raises(SystemExit):
                main()
        out = capsys.readouterr().out
        assert "7844" in out  # next_port = 7843 + 1

    def test_custom_port_collision_suggests_incremented_port(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch.object(sys, "argv", ["anjor", "start", "--port", "9000"]),
            patch("anjor.cli._check_port", return_value="other"),
        ):
            with pytest.raises(SystemExit):
                main()
        out = capsys.readouterr().out
        assert "9000" in out
        assert "9001" in out

    def test_other_process_suggests_env_var_syntax(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch.object(sys, "argv", ["anjor", "start"]),
            patch("anjor.cli._check_port", return_value="other"),
        ):
            with pytest.raises(SystemExit):
                main()
        out = capsys.readouterr().out
        assert "ANJOR_COLLECTOR_PORT" in out
        assert "anjor start" in out

    def test_other_process_does_not_call_uvicorn(self) -> None:
        mock_run = MagicMock()
        with (
            patch.object(sys, "argv", ["anjor", "start"]),
            patch("anjor.cli._check_port", return_value="other"),
            patch("uvicorn.run", mock_run),
            patch("builtins.print"),
        ):
            with pytest.raises(SystemExit):
                main()
        mock_run.assert_not_called()

    def test_check_port_called_with_configured_host_and_port(self) -> None:
        mock_check = MagicMock(return_value="free")
        mock_run = MagicMock()
        with (
            patch.object(sys, "argv", ["anjor", "start", "--port", "8888"]),
            patch("anjor.cli._check_port", mock_check),
            patch("uvicorn.run", mock_run),
            patch("builtins.print"),
        ):
            main()
        mock_check.assert_called_once_with("127.0.0.1", 8888)


# ---------------------------------------------------------------------------
# _check_port unit tests (logic only, no real network)
# ---------------------------------------------------------------------------


class TestCheckPortFree:
    def test_free_port_returns_free(self) -> None:
        with patch("socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 1  # non-zero = not connected
            mock_sock_cls.return_value.__enter__.return_value = mock_sock
            result = _check_port("127.0.0.1", 9999)
        assert result == "free"

    def test_settimeout_called(self) -> None:
        with patch("socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 1
            mock_sock_cls.return_value.__enter__.return_value = mock_sock
            _check_port("127.0.0.1", 9999)
        mock_sock.settimeout.assert_called_once_with(1)


class TestCheckPortAnjor:
    def _make_health_response(self, body: bytes, status: int = 200) -> MagicMock:
        resp = MagicMock()
        resp.status = status
        resp.read.return_value = body
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_anjor_health_shape_returns_anjor(self) -> None:
        import json

        health_body = json.dumps(
            {"status": "ok", "uptime_seconds": 10.0, "queue_depth": 0, "db_path": "anjor.db"}
        ).encode()

        with patch("socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 0  # port in use
            mock_sock_cls.return_value.__enter__.return_value = mock_sock
            with patch(
                "urllib.request.urlopen", return_value=self._make_health_response(health_body)
            ):
                result = _check_port("127.0.0.1", 7843)
        assert result == "anjor"

    def test_non_200_returns_other(self) -> None:
        with patch("socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 0
            mock_sock_cls.return_value.__enter__.return_value = mock_sock
            with patch(
                "urllib.request.urlopen",
                return_value=self._make_health_response(b"{}", status=404),
            ):
                result = _check_port("127.0.0.1", 7843)
        assert result == "other"

    def test_wrong_shape_returns_other(self) -> None:
        import json

        # Missing db_path — not an anjor response
        body = json.dumps({"status": "ok", "version": "1.0"}).encode()
        with patch("socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 0
            mock_sock_cls.return_value.__enter__.return_value = mock_sock
            with patch("urllib.request.urlopen", return_value=self._make_health_response(body)):
                result = _check_port("127.0.0.1", 7843)
        assert result == "other"

    def test_connection_refused_returns_other(self) -> None:
        import urllib.error

        with patch("socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 0
            mock_sock_cls.return_value.__enter__.return_value = mock_sock
            with patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("connection refused"),
            ):
                result = _check_port("127.0.0.1", 7843)
        assert result == "other"

    def test_non_loopback_host_uses_actual_host_in_url(self) -> None:
        """For non-loopback hosts, the health check URL should use the actual host."""
        import json

        health_body = json.dumps(
            {"status": "ok", "uptime_seconds": 1.0, "queue_depth": 0, "db_path": "anjor.db"}
        ).encode()

        captured_urls: list[str] = []

        def fake_urlopen(url: str, timeout: int) -> MagicMock:
            captured_urls.append(url)
            resp = MagicMock()
            resp.status = 200
            resp.read.return_value = health_body
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch("socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 0
            mock_sock_cls.return_value.__enter__.return_value = mock_sock
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                _check_port("0.0.0.0", 7843)  # noqa: S104

        assert len(captured_urls) == 1
        assert "0.0.0.0" in captured_urls[0]  # noqa: S104


class TestMCPAndWatchTranscriptsCommand:
    def test_mcp_command(self):
        with patch("anjor.cli._run_mcp") as mock_mcp:
            with patch.object(
                sys, "argv", ["anjor", "mcp", "--watch-transcripts", "--providers", "claude"]
            ):
                main()
            mock_mcp.assert_called_once()
            args = mock_mcp.call_args[0][0]
            assert args.watch_transcripts is True
            assert args.providers == "claude"

    def test_run_mcp_cmd(self):
        import argparse
        from anjor.cli import _run_mcp

        args = argparse.Namespace(
            watch_transcripts=True, providers="claude,gemini", port=9000, poll_interval=2.0
        )
        with patch("anjor.mcp_server.run_mcp_server") as mock_run:
            _run_mcp(args)
            mock_run.assert_called_once_with(
                watch_transcripts=True,
                providers=["claude", "gemini"],
                collector_port=9000,
                poll_interval_s=2.0,
            )

    def test_run_watch_transcripts_list(self, capsys):
        import argparse
        from anjor.cli import _run_watch_transcripts

        args = argparse.Namespace(list_providers=True)
        _run_watch_transcripts(args)
        out = capsys.readouterr().out
        assert "claude" in out

    def test_run_watch_transcripts_start(self):
        import argparse
        from anjor.cli import _run_watch_transcripts

        args = argparse.Namespace(
            list_providers=False, providers="claude", port=7843, poll_interval=2.0
        )
        with (
            patch("anjor.watchers.manager.WatcherManager.start") as mock_start,
            patch(
                "anjor.watchers.manager.WatcherManager.active_providers", return_value=["claude"]
            ),
            patch("threading.Event.wait") as mock_wait,
            patch("anjor.watchers.manager.WatcherManager.stop") as mock_stop,
        ):
            _run_watch_transcripts(args)
            mock_start.assert_called_once_with(["claude"])
            mock_wait.assert_called_once()
            mock_stop.assert_called_once()

    def test_run_watch_transcripts_no_providers(self):
        import argparse
        from anjor.cli import _run_watch_transcripts

        args = argparse.Namespace(
            list_providers=False, providers="claude", port=7843, poll_interval=2.0
        )
        with (
            patch("anjor.watchers.manager.WatcherManager.start") as mock_start,
            patch("anjor.watchers.manager.WatcherManager.active_providers", return_value=[]),
        ):
            _run_watch_transcripts(args)
            mock_start.assert_called_once()
