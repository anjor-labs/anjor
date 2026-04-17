# Installation

## Recommended: pipx

[pipx](https://pipx.pypa.io) installs Anjor into an isolated environment so it doesn't conflict with your project's dependencies and puts `anjor` on your `$PATH`.

```bash
# Install pipx if you don't have it
brew install pipx && pipx ensurepath   # macOS
# or: pip install --user pipx

# Install Anjor with MCP support (recommended)
pipx install "anjor[mcp]"

# Base install without MCP
pipx install anjor
```

Open a new terminal tab after install so `$PATH` picks up the `anjor` command.

## With pip (inside a virtualenv)

```bash
pip install "anjor[mcp]"
```

## Extras

| Extra | What it adds |
|-------|-------------|
| `anjor[mcp]` | MCP server (`anjor mcp`) — required for Claude Code / Gemini CLI integration |

## Upgrading

```bash
pipx upgrade anjor
# Note: if you cloned the repo, use: pipx install --force ".[mcp]"
```

## Verifying the install

```bash
anjor --version
anjor start --help
```
