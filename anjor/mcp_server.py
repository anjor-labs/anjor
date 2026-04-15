"""anjor MCP server — entry point for Claude Code subscription users.

Exposes one tool: anjor_status.
Auto-starts the HTTP collector in the background on startup.
Optionally starts WatcherManager when watch_transcripts=True.

.mcp.json configuration (place in project root):
    {
      "mcpServers": {
        "anjor": {
          "command": "anjor",
          "args": ["mcp"]
        }
      }
    }

With transcript watching:
    {
      "mcpServers": {
        "anjor": {
          "command": "anjor",
          "args": ["mcp", "--watch-transcripts"]
        }
      }
    }
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ── Collector lifecycle ────────────────────────────────────────────────────────


def _collector_is_running(port: int = 7843) -> bool:
    try:
        with urllib.request.urlopen(  # noqa: S310
            f"http://localhost:{port}/health", timeout=2
        ) as resp:
            data = json.loads(resp.read())
            return data.get("status") == "ok" and "db_path" in data
    except Exception:  # noqa: BLE001
        return False


def _start_collector_background(port: int = 7843) -> None:
    """Start the anjor HTTP collector in a detached subprocess. Idempotent."""
    if _collector_is_running(port):
        return
    subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "anjor.cli_runner", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # Wait up to 5 seconds for the collector to bind its port.
    for _ in range(20):
        time.sleep(0.25)
        if _collector_is_running(port):
            return


def _sanitise_mcp(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive keys in MCP input payloads."""
    from fnmatch import fnmatch

    _sensitive = ["*api_key*", "*secret*", "*password*", "*token*", "*auth*", "*bearer*"]
    result: dict[str, Any] = {}
    for k, v in payload.items():
        result[k] = "[REDACTED]" if any(fnmatch(k.lower(), p) for p in _sensitive) else v
    return result


# ── MCP server entry point ────────────────────────────────────────────────────


def run_mcp_server(
    watch_transcripts: bool = False,
    providers: list[str] | None = None,
    collector_port: int = 7843,
) -> None:
    """Start the anjor MCP server. Exits 1 if mcp SDK is not installed."""
    try:
        import mcp.server.stdio
        import mcp.types as mcp_types
        from mcp.server import Server
    except ImportError:
        print("MCP support requires: pip install anjor[mcp]", file=sys.stderr)
        sys.exit(1)

    collector_url = f"http://localhost:{collector_port}"

    # Start collector (background, idempotent).
    _start_collector_background(collector_port)

    # Optionally start transcript watchers.
    if watch_transcripts:
        try:
            from anjor.watchers.manager import WatcherManager

            manager = WatcherManager(collector_url=collector_url)
            manager.start(providers)
            active = manager.active_providers()
            if active:
                print(
                    f"anjor: transcript watcher active — providers: {', '.join(active)}",
                    file=sys.stderr,
                )
        except Exception as exc:
            # Watcher failure must NEVER block MCP server startup.
            logger.warning("watcher_start_failed", error=str(exc))
            print(
                f"anjor: transcript watcher failed to start ({exc}) — continuing without it",
                file=sys.stderr,
            )

    server: Server = Server("anjor")

    @server.list_tools()  # type: ignore[untyped-decorator]
    async def list_tools() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name="anjor_status",
                description=(
                    "Returns current session statistics from the anjor observability "
                    "platform: total tool calls, LLM calls, failure count, and top tools."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            )
        ]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[mcp_types.TextContent]:
        import time as _time

        import httpx as _httpx

        from anjor.analysis.drift.fingerprint import fingerprint
        from anjor.core.events.tool_call import (
            FailureType,
            ToolCallEvent,
            ToolCallStatus,
        )

        start = _time.monotonic()

        if name != "anjor_status":
            return [mcp_types.TextContent(type="text", text=f"Unknown tool: {name}")]

        result_text = "{}"
        is_error = False
        try:
            async with _httpx.AsyncClient(timeout=5.0) as client:
                tc_resp = await client.get(f"{collector_url}/tools")
                llm_resp = await client.get(f"{collector_url}/llm")

            tc_data = tc_resp.json() if tc_resp.status_code == 200 else {}
            llm_data = llm_resp.json() if llm_resp.status_code == 200 else {}

            tools = tc_data.get("tools", [])
            total_calls = sum(t.get("call_count", 0) for t in tools)
            failure_count = sum(t.get("failure_count", 0) for t in tools)
            top_tools = sorted(tools, key=lambda t: t.get("call_count", 0), reverse=True)[:5]
            llm_calls = sum(m.get("call_count", 0) for m in llm_data.get("models", []))

            status: dict[str, Any] = {
                "total_tool_calls": total_calls,
                "total_llm_calls": llm_calls,
                "failure_count": failure_count,
                "top_tools": [
                    {"name": t["name"], "calls": t.get("call_count", 0)} for t in top_tools
                ],
            }
            result_text = json.dumps(status, indent=2)
        except Exception as exc:
            is_error = True
            result_text = json.dumps({"error": str(exc)})

        latency_ms = (_time.monotonic() - start) * 1000

        # Emit ToolCallEvent for this anjor_status call.
        try:
            sanitised_args = _sanitise_mcp(arguments)
            output: dict[str, Any] = {"result": result_text[:500]}
            event = ToolCallEvent(
                tool_name="anjor_status",
                status=ToolCallStatus.FAILURE if is_error else ToolCallStatus.SUCCESS,
                failure_type=FailureType.API_ERROR if is_error else None,
                latency_ms=latency_ms,
                input_payload=sanitised_args,
                output_payload=output,
                input_schema_hash=fingerprint(sanitised_args),
                output_schema_hash=fingerprint(output),
                source="mcp",
            )
            _httpx.post(
                f"{collector_url}/events",
                json=event.model_dump(mode="json"),
                timeout=2.0,
            )
        except Exception as exc:
            logger.warning("mcp_event_emit_error", error=str(exc))

        return [mcp_types.TextContent(type="text", text=result_text)]

    print(
        f"anjor MCP server ready — dashboard at {collector_url}/ui/",
        file=sys.stderr,
    )

    import asyncio

    asyncio.run(mcp.server.stdio.stdio_server(server))
