"""Tests for the anjor CLI entry point."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from anjor.cli import main


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
            patch("uvicorn.run", mock_run),
            patch("builtins.print"),
        ):
            main()
        mock_run.assert_called_once()

    def test_start_prints_urls(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_run = MagicMock()
        with (
            patch.object(sys, "argv", ["anjor", "start"]),
            patch("uvicorn.run", mock_run),
        ):
            main()
        out = capsys.readouterr().out
        assert "7843" in out
        assert "dashboard" in out.lower() or "/ui/" in out
