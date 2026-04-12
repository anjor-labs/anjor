# anjor/interceptors

HTTP interception — captures agent traffic without code changes.

## Key abstractions

- **`PatchInterceptor`** — monkey-patches `httpx.Client.send` and `AsyncClient.send`. Thread-safe, idempotent install/uninstall. On every request, routes through `ParserRegistry` and puts events onto `EventPipeline`. Never raises into the agent.
- **`ProxyInterceptor`** — mitmproxy sidecar stub. Requires `pip install anjor[proxy]`. Not implemented in Phase 1.
- **`parsers/AnthropicParser`** — extracts `tool_use` blocks from Anthropic API responses → `ToolCallEvent`. Sanitises payloads.
- **`parsers/ParserRegistry`** — first-match URL routing to parsers.

## Architecture fit

Interceptors sit above the agent's HTTP layer and below the pipeline. They translate raw HTTP into domain events.

## Extension

New API provider: implement `BaseParser`, register in `build_default_registry()`.
