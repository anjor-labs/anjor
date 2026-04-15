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
    start.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port (default: 7843, or ANJOR_COLLECTOR_PORT env var)",
    )
    start.add_argument("--db", default=None, help="SQLite DB path (default: anjor.db)")
    start.add_argument("--log-level", default=None, help="Log level (default: INFO)")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "start":
        _start(args)


def _check_port(host: str, port: int) -> str:
    """Check whether *port* on *host* is free, an anjor collector, or something else.

    Returns one of:
      ``"free"``  — nothing is bound to the port; safe to start.
      ``"anjor"`` — an anjor collector is already running there.
      ``"other"`` — some other process is using the port.

    Uses stdlib only (socket + urllib.request) to avoid circular imports and to
    keep this function usable before the anjor package is fully initialised.
    """
    import json
    import socket
    import urllib.request

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        in_use = sock.connect_ex((host, port)) == 0

    if not in_use:
        return "free"

    # Something is listening — probe /health to tell anjor from other processes.
    # Anjor's health response always has {"status": "ok", "db_path": ..., "queue_depth": ...}.
    try:
        check_host = "localhost" if host == "127.0.0.1" else host
        url = f"http://{check_host}:{port}/health"
        with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310
            if resp.status == 200:
                data = json.loads(resp.read())
                if data.get("status") == "ok" and "db_path" in data and "queue_depth" in data:
                    return "anjor"
    except Exception:  # noqa: BLE001, S110
        pass  # not an anjor instance — fall through to "other"

    return "other"


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

    display_host = "localhost" if config.host == "127.0.0.1" else config.host
    url = f"http://{display_host}:{config.collector_port}"

    state = _check_port(config.host, config.collector_port)
    if state == "anjor":
        print(f"anjor is already running at {url}/ui/")
        sys.exit(0)
    if state == "other":
        next_port = config.collector_port + 1
        print(f"Port {config.collector_port} is already in use.")
        print(
            f"Start anjor on a different port with:  ANJOR_COLLECTOR_PORT={next_port} anjor start"
        )
        sys.exit(1)

    app = create_app(config=config)
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
