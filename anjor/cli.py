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
    start.add_argument(
        "--watch-transcripts",
        action="store_true",
        default=False,
        help="Also watch AI coding agent transcript files (Claude Code, Gemini CLI, etc.)",
    )
    start.add_argument(
        "--providers",
        default=None,
        help=(
            "Comma-separated provider keys to watch (default: auto-detect). "
            "Options: claude, gemini, codex, antigravity. "
            "Only used with --watch-transcripts."
        ),
    )
    start.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Transcript polling interval in seconds (default: 2.0). Only used with --watch-transcripts.",  # noqa: E501
    )
    start.add_argument(
        "--project",
        default="",
        help=(
            "Project name tag for all ingested events (overrides auto-detection). "
            "Only used with --watch-transcripts."
        ),
    )
    start.add_argument(
        "--no-capture-messages",
        dest="no_capture_messages",
        action="store_true",
        default=False,
        help="Disable message capture (overrides config default of on).",
    )

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
    mcp_cmd.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Transcript polling interval in seconds (default: 2.0)",
    )
    mcp_cmd.add_argument(
        "--project",
        default="",
        help="Project name tag for all ingested events (overrides auto-detection).",
    )
    mcp_cmd.add_argument(
        "--no-capture-messages",
        dest="no_capture_messages",
        action="store_true",
        default=False,
        help="Disable message capture (overrides config default of on).",
    )

    status_cmd = sub.add_parser("status", help="Show a compact session health summary")
    status_cmd.add_argument("--port", type=int, default=7843, help="Collector port (default: 7843)")
    status_cmd.add_argument(
        "--since-minutes",
        type=int,
        default=120,
        help="Look-back window in minutes (default: 120)",
    )
    status_cmd.add_argument("--project", default=None, help="Filter to a specific project tag")

    report_cmd = sub.add_parser(
        "report",
        help="Generate a quality report; exit 1 if assertions fail, 2 if no data",
    )
    report_cmd.add_argument(
        "--session",
        metavar="SESSION",
        default=None,
        help="Session to report on. Pass 'last' to use the most recent session.",
    )
    report_cmd.add_argument(
        "--since",
        metavar="WINDOW",
        default=None,
        help="Time window, e.g. '2h' or '30m' (default: 2h, ignored when --session is set)",
    )
    report_cmd.add_argument(
        "--assert",
        dest="assertions",
        action="append",
        default=[],
        metavar="EXPR",
        help=(
            "Assertion expression, e.g. 'success_rate >= 0.95'. "
            "Supported metrics: success_rate, p95_latency_ms, failure_count, total_cost_usd. "
            "Can be repeated."
        ),
    )
    report_cmd.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output format (default: text)",
    )
    report_cmd.add_argument("--project", default=None, help="Filter to a specific project tag")
    report_cmd.add_argument(
        "--db",
        default=None,
        help="SQLite DB path (default: ~/.anjor/anjor.db)",
    )

    diff_cmd = sub.add_parser(
        "diff",
        help="Compare current window vs prior window; detect regressions",
    )
    diff_cmd.add_argument(
        "--window",
        metavar="WINDOW",
        default="24h",
        help="Window size, e.g. '24h', '7d', '30m' (default: 24h). "  # noqa: E501
        "Current = last window; prior = window before that.",
    )
    diff_cmd.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output format (default: text)",
    )
    diff_cmd.add_argument("--project", default=None, help="Filter to a specific project tag")
    diff_cmd.add_argument(
        "--db",
        default=None,
        help="SQLite DB path (default: ~/.anjor/anjor.db)",
    )

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
    wt_cmd.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Transcript polling interval in seconds (default: 2.0)",
    )
    wt_cmd.add_argument(
        "--project",
        default="",
        help="Project name tag for all ingested events (overrides auto-detection).",
    )
    wt_cmd.add_argument(
        "--no-capture-messages",
        dest="no_capture_messages",
        action="store_true",
        default=False,
        help="Disable message capture (overrides config default of on).",
    )

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
    elif args.command == "status":
        _run_status(args)
    elif args.command == "report":
        _run_report(args)
    elif args.command == "diff":
        _run_diff(args)
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

    if args.watch_transcripts:
        from anjor.watchers.manager import WatcherManager

        providers = (
            [p.strip() for p in args.providers.split(",") if p.strip()] if args.providers else None
        )
        capture = config.capture_messages and not args.no_capture_messages
        manager = WatcherManager(
            collector_url=f"http://localhost:{config.collector_port}",
            poll_interval=args.poll_interval,
            project=args.project,
            capture_messages=capture,
        )
        manager.start(providers)
        active = manager.active_providers()
        if active:
            print(f"Watching          {', '.join(active)}")

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
        poll_interval_s=args.poll_interval,
        project=args.project,
        capture_messages=not args.no_capture_messages,
    )


def _run_status(args: argparse.Namespace) -> None:
    import urllib.error
    import urllib.parse
    import urllib.request

    from anjor.analysis.advisor import SessionAdvisor

    port: int = args.port
    since_minutes: int = args.since_minutes
    project: str | None = args.project

    base_url = f"http://localhost:{port}"

    def _fetch(path: str) -> list[dict]:  # type: ignore[type-arg]
        params: dict[str, object] = {"since_minutes": since_minutes}
        if project:
            params["project"] = project
        query = urllib.parse.urlencode(params)
        url = f"{base_url}{path}?{query}"
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310
                import json

                return json.loads(resp.read())  # type: ignore[no-any-return]
        except urllib.error.URLError:
            return []

    tools = _fetch("/tools")
    llm_models = _fetch("/llm")

    advisor = SessionAdvisor()
    insights = advisor.analyse(tools=tools, llm_models=llm_models)
    summary = advisor.format_summary(
        tools=tools,
        llm_models=llm_models,
        since_minutes=since_minutes,
        insights=insights,
    )

    if not tools and not llm_models:
        print(f"anjor: no data (is the collector running on port {port}?)")
        sys.exit(2)

    print(summary)


def _parse_since(since: str) -> int:
    """Parse a window string like '2h' or '30m' into minutes."""
    since = since.strip()
    if since.endswith("h"):
        return int(since[:-1]) * 60
    if since.endswith("m"):
        return int(since[:-1])
    if since.endswith("d"):
        return int(since[:-1]) * 1440
    raise ValueError(f"unrecognised window format: {since!r} (use e.g. '2h', '30m')")


def _run_report(args: argparse.Namespace) -> None:
    import asyncio
    from pathlib import Path

    from anjor.analysis.report import ReportGenerator
    from anjor.collector.storage.sqlite import SQLiteBackend

    db_path = args.db or str(Path.home() / ".anjor" / "anjor.db")
    project: str | None = args.project
    fmt: str = args.format
    assertions: list[str] = args.assertions

    since_minutes: int
    if args.session == "last":
        since_minutes = asyncio.run(_find_last_session_minutes(db_path))
    elif args.since:
        try:
            since_minutes = _parse_since(args.since)
        except ValueError as exc:
            print(f"anjor: {exc}", file=sys.stderr)
            sys.exit(2)
    else:
        since_minutes = 120

    async def _query() -> tuple[list[object], list[object]]:
        backend = SQLiteBackend(db_path=db_path)
        await backend.connect()
        try:
            tools = await backend.list_tool_summaries(project=project, since_minutes=since_minutes)
            llm_models = await backend.list_llm_summaries(
                project=project, since_minutes=since_minutes
            )
        finally:
            await backend.close()
        return tools, llm_models  # type: ignore[return-value]

    tools, llm_models = asyncio.run(_query())

    if not tools and not llm_models:
        print("anjor: no data in window (is the DB path correct, or try a wider --since window?)")
        sys.exit(2)

    gen = ReportGenerator()
    data = gen.generate(tools, llm_models, since_minutes=since_minutes, project=project)
    results = gen.evaluate_assertions(assertions, data)

    if fmt == "json":
        print(gen.format_json(data, results))
    elif fmt == "markdown":
        print(gen.format_markdown(data, results))
    else:
        print(gen.format_text(data, results))

    if results and not all(r.passed for r in results):
        sys.exit(1)


def _run_diff(args: argparse.Namespace) -> None:
    import asyncio
    from pathlib import Path

    from anjor.analysis.report import DiffReport

    db_path = args.db or str(Path.home() / ".anjor" / "anjor.db")
    project: str | None = args.project
    fmt: str = args.format

    try:
        window_minutes = _parse_since(args.window)
    except ValueError as exc:
        print(f"anjor: {exc}", file=sys.stderr)
        sys.exit(2)

    current_rows, prior_rows, cur_token, pri_token = asyncio.run(
        _query_diff_windows(db_path, window_minutes, project)
    )

    if not current_rows and not prior_rows:
        print("anjor: no data in either window (is the DB path correct, or try a wider --window?)")
        sys.exit(2)

    gen = DiffReport()
    data = gen.generate(
        current_rows,
        prior_rows,
        window_minutes=window_minutes,
        project=project,
        current_avg_token_input=cur_token,
        prior_avg_token_input=pri_token,
    )

    if fmt == "json":
        print(gen.format_json(data))
    elif fmt == "markdown":
        print(gen.format_markdown(data))
    else:
        print(gen.format_text(data))


async def _query_diff_windows(
    db_path: str,
    window_minutes: int,
    project: str | None,
) -> tuple[list[dict[str, object]], list[dict[str, object]], float, float]:
    """Return (current_rows, prior_rows, current_avg_token, prior_avg_token)."""
    from datetime import UTC, datetime, timedelta

    import aiosqlite

    now = datetime.now(UTC)
    t1 = now - timedelta(minutes=window_minutes)  # current window start
    t2 = now - timedelta(minutes=2 * window_minutes)  # prior window start

    proj_clause = " AND project = ?" if project else ""
    proj_params = [project] if project else []

    try:
        async with aiosqlite.connect(db_path) as conn:
            conn.row_factory = aiosqlite.Row

            async def _tool_rows(since: datetime, until: datetime) -> list[dict[str, object]]:
                params: list[object] = [since.isoformat(), until.isoformat(), *proj_params]
                cur = await conn.execute(
                    f"SELECT tool_name, status, latency_ms FROM tool_calls"  # noqa: S608
                    f" WHERE timestamp >= ? AND timestamp < ?{proj_clause}",
                    params,
                )
                return [dict(r) for r in await cur.fetchall()]

            async def _avg_token(since: datetime, until: datetime) -> float:
                params: list[object] = [since.isoformat(), until.isoformat(), *proj_params]
                cur = await conn.execute(
                    f"SELECT AVG(token_input) FROM llm_calls"  # noqa: S608
                    f" WHERE timestamp >= ? AND timestamp < ?{proj_clause}",
                    params,
                )
                row = await cur.fetchone()
                return float(row[0] or 0.0) if row else 0.0

            current_rows = await _tool_rows(t1, now)
            prior_rows = await _tool_rows(t2, t1)
            cur_token = await _avg_token(t1, now)
            pri_token = await _avg_token(t2, t1)

    except Exception:  # noqa: BLE001, S110
        return [], [], 0.0, 0.0

    return current_rows, prior_rows, cur_token, pri_token


async def _find_last_session_minutes(db_path: str) -> int:
    """Return minutes since the most recent session's earliest event."""
    from datetime import UTC, datetime

    import aiosqlite

    try:
        async with aiosqlite.connect(db_path) as conn:
            cur = await conn.execute(
                """
                SELECT MIN(timestamp) FROM tool_calls
                WHERE session_id = (
                    SELECT session_id FROM tool_calls
                    ORDER BY timestamp DESC LIMIT 1
                )
                """
            )
            row = await cur.fetchone()
            if row and row[0]:
                start = datetime.fromisoformat(row[0])
                if start.tzinfo is None:
                    start = start.replace(tzinfo=UTC)
                delta = datetime.now(UTC) - start
                return max(1, int(delta.total_seconds() / 60) + 1)
    except Exception:  # noqa: BLE001, S110
        pass
    return 120  # fallback


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

    from anjor.core.config import AnjorConfig
    from anjor.watchers.manager import WatcherManager

    _cfg = AnjorConfig()
    capture = _cfg.capture_messages and not args.no_capture_messages
    manager = WatcherManager(
        collector_url=collector_url,
        poll_interval=args.poll_interval,
        project=args.project,
        capture_messages=capture,
    )
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
