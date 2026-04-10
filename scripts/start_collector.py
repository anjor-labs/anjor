#!/usr/bin/env python3
"""Start the AgentScope collector service.

Usage:
    python scripts/start_collector.py
    python scripts/start_collector.py --port 7843 --db agentscope.db
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from agentscope.collector.api.app import create_app
from agentscope.core.config import AgentScopeConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentScope Collector")
    parser.add_argument("--port", type=int, default=None, help="Collector port (default: 7843)")
    parser.add_argument("--db", type=str, default=None, help="SQLite DB path")
    parser.add_argument("--log-level", default=None, help="Log level")
    args = parser.parse_args()

    kwargs: dict = {}
    if args.port:
        kwargs["collector_port"] = args.port
    if args.db:
        kwargs["db_path"] = args.db
    if args.log_level:
        kwargs["log_level"] = args.log_level.upper()

    config = AgentScopeConfig(**kwargs)  # type: ignore[arg-type]
    app = create_app(config=config)

    print(f"Starting AgentScope Collector on port {config.collector_port}")
    print(f"Database: {config.db_path}")
    print(f"Health: http://localhost:{config.collector_port}/health")

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=config.collector_port,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    main()
