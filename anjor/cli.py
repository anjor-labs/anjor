"""CLI entry point for Anjor.

Usage:
    anjor start                          # collector + dashboard on :7843
    anjor start --port 8000 --db my.db
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="anjor",
        description="Anjor — observability for AI agents",
    )
    sub = parser.add_subparsers(dest="command")

    start = sub.add_parser("start", help="Start the collector and dashboard")
    start.add_argument("--host", default=None, help="Bind host (default: 127.0.0.1)")
    start.add_argument("--port", type=int, default=None, help="Port (default: 7843)")
    start.add_argument("--db", default=None, help="SQLite DB path (default: anjor.db)")
    start.add_argument("--log-level", default=None, help="Log level (default: INFO)")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "start":
        _start(args)


def _start(args: argparse.Namespace) -> None:
    import uvicorn

    from anjor.collector.api.app import create_app
    from anjor.core.config import AnjorConfig

    kwargs: dict[str, object] = {}
    if args.host:
        kwargs["host"] = args.host
    if args.port:
        kwargs["collector_port"] = args.port
    if args.db:
        kwargs["db_path"] = args.db
    if args.log_level:
        kwargs["log_level"] = args.log_level.upper()

    config = AnjorConfig(**kwargs)  # type: ignore[arg-type]
    app = create_app(config=config)

    display_host = "localhost" if config.host == "127.0.0.1" else config.host
    url = f"http://{display_host}:{config.collector_port}"
    print(f"Anjor collector  {url}/health")
    print(f"Anjor dashboard  {url}/ui/")
    print(f"Database         {config.db_path}")

    uvicorn.run(
        app,
        host=config.host,
        port=config.collector_port,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    main()
