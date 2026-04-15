import sys
from unittest.mock import MagicMock, patch

from anjor.cli_runner import main


def test_cli_runner_main():
    mock_run = MagicMock()
    with (
        patch.object(
            sys, "argv", ["cli_runner", "--port", "8000", "--host", "0.0.0.0", "--db", "test.db"]
        ),
        patch("uvicorn.run", mock_run),
    ):
        main()
    mock_run.assert_called_once()
    _, kwargs = mock_run.call_args
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 8000
    assert kwargs["log_level"] == "warning"
