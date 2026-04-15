"""MCP tool name parsing helpers.

MCP clients name tools using the convention ``mcp__<server>__<tool>``.
These helpers normalise and validate that convention in pure Python, making
them usable in tests, analytics pipelines, and user code independently of the
storage layer.

Parsing rule
------------
The **first** ``__`` (double-underscore) after the ``mcp__`` prefix is the
server/tool boundary.  This means:

- Server names that contain single underscores are fine
  (``brave_search``, ``my_server``).
- Tool names that contain ``__`` are supported — only the *first* ``__``
  is treated as a separator, the rest becomes part of the tool name
  (``mcp__server__tool__with__extras`` → server ``server``, tool
  ``tool__with__extras``).
- A server name that itself contains ``__`` is ambiguous with the separator
  and cannot be represented unambiguously; in practice MCP server identifiers
  use single underscores.

A name is considered **invalid** (returns ``None`` / ``False``) if:
- It does not start with the literal prefix ``mcp__``.
- The server segment (between ``mcp__`` and the first ``__``) is empty.
- There is no separator ``__`` after the prefix, i.e. no tool segment exists.
- The tool segment (after the separator) is empty.
"""

from __future__ import annotations

__all__ = ["is_mcp_tool", "parse_mcp_tool_name"]

_MCP_PREFIX = "mcp__"
_SEP = "__"


def is_mcp_tool(name: str) -> bool:
    """Return ``True`` if *name* follows the ``mcp__<server>__<tool>`` convention.

    A valid MCP tool name:
    - starts with the literal prefix ``mcp__`` (case-sensitive)
    - has a non-empty server segment before the first ``__`` separator
    - has a non-empty tool segment after the separator

    Examples::

        >>> is_mcp_tool("mcp__github__create_pr")
        True
        >>> is_mcp_tool("mcp__brave_search__web_search")
        True
        >>> is_mcp_tool("web_search")
        False
        >>> is_mcp_tool("mcp__notvalid")   # missing second __
        False
        >>> is_mcp_tool("mcp____tool")     # empty server segment
        False
        >>> is_mcp_tool("mcp__server__")   # empty tool segment
        False
    """
    return parse_mcp_tool_name(name) is not None


def parse_mcp_tool_name(name: str) -> tuple[str, str] | None:
    """Parse ``mcp__<server>__<tool>`` into ``(server, tool)``.

    Returns ``None`` for any name that does not match the convention.

    The first ``__`` after the ``mcp__`` prefix is the separator, so tool
    names that themselves contain ``__`` are handled correctly::

        >>> parse_mcp_tool_name("mcp__github__create_pr")
        ('github', 'create_pr')
        >>> parse_mcp_tool_name("mcp__brave_search__web_search")
        ('brave_search', 'web_search')
        >>> parse_mcp_tool_name("mcp__server__tool__with__extras")
        ('server', 'tool__with__extras')
        >>> parse_mcp_tool_name("mcp__notvalid") is None
        True
        >>> parse_mcp_tool_name("web_search") is None
        True
        >>> parse_mcp_tool_name("") is None
        True
    """
    if not name.startswith(_MCP_PREFIX):
        return None
    rest = name[len(_MCP_PREFIX) :]  # e.g. "github__create_pr"
    sep_idx = rest.find(_SEP)
    # sep_idx == -1 → no separator (e.g. "mcp__notvalid")
    # sep_idx ==  0 → empty server segment (e.g. "mcp____tool")
    if sep_idx <= 0:
        return None
    server = rest[:sep_idx]
    tool = rest[sep_idx + len(_SEP) :]
    if not tool:  # empty tool segment (e.g. "mcp__server__")
        return None
    return (server, tool)
