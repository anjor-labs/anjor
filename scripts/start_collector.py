#!/usr/bin/env python3
"""Start the Anjor collector service.

Usage:
    python scripts/start_collector.py
    python scripts/start_collector.py --port 7843 --db anjor.db
"""

from __future__ import annotations

import argparse

import uvicorn

from anjor.collector.api.app import create_app
from anjor.core.config import AnjorConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Anjor Collector")
    parser.add_argument("--host", type=str, default=None, help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Collector port (default: 7843)")
    parser.add_argument("--db", type=str, default=None, help="SQLite DB path")
    parser.add_argument("--log-level", default=None, help="Log level")
    args = parser.parse_args()

    kwargs: dict = {}
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

    print(f"Starting Anjor Collector on port {config.collector_port}")
    print(f"Database: {config.db_path}")
    print(f"Health: http://localhost:{config.collector_port}/health")

    uvicorn.run(
        app,
        host=config.host,
        port=config.collector_port,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    main()
