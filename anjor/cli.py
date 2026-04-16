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
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the anjor version and exit",
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

    mcp_cmd = sub.add_parser("mcp", help="Start anjor as an MCP server (for Claude Code)")
    mcp_cmd.add_argument(
        "--watch-transcripts",
        action="store_true",
        default=False,
        help="Also watch AI coding agent transcript files for LLM token data",
    )
    mcp_cmd.add_argument(
        "--providers",
        default=None,
        help=(
            "Comma-separated provider keys to watch (default: auto-detect). "
            "Options: claude, gemini, codex, antigravity"
        ),
    )
    mcp_cmd.add_argument("--port", type=int, default=7843, help="Collector port (default: 7843)")

    wt_cmd = sub.add_parser(
        "watch-transcripts",
        help="Watch AI coding agent transcript files (standalone)",
    )
    wt_cmd.add_argument(
        "--providers",
        default=None,
        help="Comma-separated provider keys (default: auto-detect)",
    )
    wt_cmd.add_argument(
        "--list-providers",
        action="store_true",
        default=False,
        help="Print all registered providers and whether their paths exist, then exit",
    )
    wt_cmd.add_argument("--port", type=int, default=7843, help="Collector port (default: 7843)")

    args = parser.parse_args()

    if args.version:
        from anjor import __version__

        print(f"anjor {__version__}")
        sys.exit(0)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "start":
        _start(args)
    elif args.command == "mcp":
        _run_mcp(args)
    elif args.command == "watch-transcripts":
        _run_watch_transcripts(args)


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


def _run_mcp(args: argparse.Namespace) -> None:
    from anjor.mcp_server import run_mcp_server

    providers = (
        [p.strip() for p in args.providers.split(",") if p.strip()] if args.providers else None
    )
    run_mcp_server(
        watch_transcripts=args.watch_transcripts,
        providers=providers,
        collector_port=args.port,
    )


def _run_watch_transcripts(args: argparse.Namespace) -> None:
    import glob as _glob
    import signal
    import threading

    from anjor.watchers.registry import WATCHER_REGISTRY

    if args.list_providers:
        home = str(__import__("pathlib").Path.home())
        for key, cls in WATCHER_REGISTRY.items():
            w = cls()
            paths = w.default_paths()
            found = any(_glob.glob(p, recursive=True) for p in paths)
            short = paths[0].replace(home, "~").split("**")[0].rstrip("/")
            mark = "✓" if found else "✗"
            status = "found" if found else "not found"
            print(f"  {key:<14} {mark} {short} ({status})")
        return

    providers = (
        [p.strip() for p in args.providers.split(",") if p.strip()] if args.providers else None
    )
    collector_url = f"http://localhost:{args.port}"

    from anjor.watchers.manager import WatcherManager

    manager = WatcherManager(collector_url=collector_url)
    manager.start(providers)

    if not manager.active_providers():
        return  # message already printed by WatcherManager.start()

    stop = threading.Event()

    def _handle_signal(sig: int, frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    print("anjor: watching transcripts — Ctrl+C to stop")
    stop.wait()
    manager.stop()


if __name__ == "__main__":
    main()
