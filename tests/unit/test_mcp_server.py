import sys
from unittest.mock import MagicMock, patch

if "mcp" not in sys.modules:
    mock_mcp = MagicMock()
    sys.modules["mcp"] = mock_mcp
    sys.modules["mcp.server"] = MagicMock()
    sys.modules["mcp.server.stdio"] = MagicMock()
    sys.modules["mcp.types"] = MagicMock()

import pytest

from anjor.mcp_server import _collector_is_running, _sanitise_mcp, run_mcp_server


def test_collector_is_running():
    with patch("urllib.request.urlopen") as mock_url:
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"status": "ok", "db_path": ":memory:"}'
        mock_url.return_value.__enter__.return_value = mock_response
        assert _collector_is_running()


def test_collector_is_running_false():
    with patch("urllib.request.urlopen") as mock_url:
        mock_url.side_effect = Exception("conn ref")
        assert not _collector_is_running()


def test_sanitise_mcp():
    out = _sanitise_mcp({"api_key": "secret", "normal": "val"})
    assert out["api_key"] == "[REDACTED]"
    assert out["normal"] == "val"


def test_run_mcp_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "mcp.server.stdio", None)

    with patch("builtins.__import__", side_effect=ImportError("mocked import error")):
        with pytest.raises(SystemExit) as exc_info:
            run_mcp_server()
        assert exc_info.value.code == 1


def test_start_collector_background_not_running():
    from anjor.mcp_server import _start_collector_background

    with (
        patch("anjor.mcp_server._collector_is_running", side_effect=[False, True]),
        patch("subprocess.Popen") as mock_popen,
        patch("time.sleep"),
    ):
        _start_collector_background(7843)
        mock_popen.assert_called_once()


def test_start_collector_background_already_running():
    from anjor.mcp_server import _start_collector_background

    with (
        patch("anjor.mcp_server._collector_is_running", return_value=True),
        patch("subprocess.Popen") as mock_popen,
    ):
        _start_collector_background(7843)
        mock_popen.assert_not_called()


def test_run_mcp_server_watch_transcripts_success():
    with (
        patch("anjor.mcp_server._start_collector_background"),
        patch("anjor.watchers.manager.WatcherManager.start") as mock_start,
        patch("anjor.watchers.manager.WatcherManager.active_providers", return_value=["claude"]),
        patch("mcp.server.Server"),
        patch("mcp.server.stdio.stdio_server"),
        patch("asyncio.run"),
    ):
        run_mcp_server(watch_transcripts=True, providers=["claude"])
        mock_start.assert_called_once_with(["claude"])


def test_run_mcp_server_watch_transcripts_exception():
    with (
        patch("anjor.mcp_server._start_collector_background"),
        patch("anjor.watchers.manager.WatcherManager.start", side_effect=Exception("watch error")),
        patch("mcp.server.Server"),
        patch("mcp.server.stdio.stdio_server"),
        patch("asyncio.run"),
    ):
        run_mcp_server(watch_transcripts=True, providers=["claude"])


@pytest.mark.asyncio
async def test_run_mcp_server_tools():
    with (
        patch("anjor.mcp_server._start_collector_background"),
        patch("mcp.server.stdio.stdio_server"),
        patch("asyncio.run"),
    ):
        tools_registered: dict = {}

        class FakeServer:
            def __init__(self, name: str) -> None:
                self.name = name

            def list_tools(self):  # noqa: ANN201
                def decorator(func):  # noqa: ANN001,ANN202
                    tools_registered["list_tools"] = func
                    return func

                return decorator

            def call_tool(self):  # noqa: ANN201
                def decorator(func):  # noqa: ANN001,ANN202
                    tools_registered["call_tool"] = func
                    return func

                return decorator

        with patch("mcp.server.Server", FakeServer):
            run_mcp_server(collector_port=7843)

        assert "list_tools" in tools_registered
        assert "call_tool" in tools_registered

        list_funcs = tools_registered["list_tools"]
        call_funcs = tools_registered["call_tool"]

        # Test list_tools — mcp_types.Tool is a mock; verify it was called with name=anjor_status
        import mcp.types as mcp_types_mod

        mcp_types_mod.Tool.reset_mock()
        await list_funcs()
        tool_call_kwargs = mcp_types_mod.Tool.call_args
        assert tool_call_kwargs is not None
        assert tool_call_kwargs.kwargs.get("name") == "anjor_status"

        # Test call_tool unknown — TextContent is mocked; capture the text= kwarg
        mcp_types_mod.TextContent.reset_mock()
        await call_funcs("unknown", {})
        tc_call = mcp_types_mod.TextContent.call_args
        assert tc_call is not None
        text_arg = tc_call.kwargs.get("text", "")
        assert "Unknown tool" in text_arg

        # Test call_tool success
        class MockResponse:
            def __init__(self, status_code: int, data: dict) -> None:
                self.status_code = status_code
                self._data = data

            def json(self) -> dict:
                return self._data

        async def mock_get(url: str, **kwargs) -> MockResponse:  # noqa: ANN003
            if "tools" in url:
                return MockResponse(200, {"tools": [{"name": "fake", "call_count": 5}]})
            return MockResponse(200, {"models": [{"name": "fake", "call_count": 2}]})

        with patch("httpx.AsyncClient.get", side_effect=mock_get), patch("httpx.post") as mock_post:
            mcp_types_mod.TextContent.reset_mock()
            await call_funcs("anjor_status", {})
            tc_call = mcp_types_mod.TextContent.call_args
            text_arg = tc_call.kwargs.get("text", "")
            assert "total_tool_calls" in text_arg
            assert "5" in text_arg
            mock_post.assert_called_once()

        # Test call_tool HTTP error
        async def mock_get_err(url: str, **kwargs) -> None:  # noqa: ANN003
            raise Exception("api down")  # noqa: TRY002

        with (
            patch("httpx.AsyncClient.get", side_effect=mock_get_err),
            patch("httpx.post") as mock_post,
        ):
            mcp_types_mod.TextContent.reset_mock()
            await call_funcs("anjor_status", {})
            tc_call = mcp_types_mod.TextContent.call_args
            text_arg = tc_call.kwargs.get("text", "")
            assert "api down" in text_arg
            mock_post.assert_called_once()
