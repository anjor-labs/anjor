"""Thin subprocess shim: python -m anjor.cli_runner --port N

Used by mcp_server._start_collector_background() to launch the HTTP
collector as a detached child process without importing the full CLI.
"""

from __future__ import annotations

import argparse


def main() -> None:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--port", type=int, default=7843)
    p.add_argument("--host", default=None)
    p.add_argument("--db", default=None)
    args = p.parse_args()

    import uvicorn

    from anjor.collector.api.app import create_app
    from anjor.core.config import AnjorConfig

    kwargs: dict[str, object] = {"collector_port": args.port}
    if args.host:
        kwargs["host"] = args.host
    if args.db:
        kwargs["db_path"] = args.db

    config = AnjorConfig(**kwargs)  # type: ignore[arg-type]
    app = create_app(config=config)
    uvicorn.run(app, host=config.host, port=config.collector_port, log_level="warning")


if __name__ == "__main__":
    main()
