"""
Sprint 2, Item #6: Schema Size Reduction

Strips pydantic's auto-generated "title" fields from tool schema properties.
These are decorative (e.g. "title": "Unique Id" next to a property named
unique_id) and add ~2,300 tokens to tool definitions that every MCP client
pays on every session before a single tool is called.

Adapted from devGPL fork's limpar_titulos_do_schema(). Operates on FastMCP
internals (_tool_manager._tools) with graceful fallback — an mcp release
that moves these internals leaves tool definitions unstripped rather than
crashing the server. Validation is unaffected because argument checking uses
the pydantic model, not the published JSON schema.
"""

import logging

logger = logging.getLogger(__name__)


def _strip_titles(node):
    """Recursively remove 'title' keys from a schema dict/list."""
    if isinstance(node, dict):
        return {k: _strip_titles(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


def strip_schema_titles(server) -> int:
    """Remove decorative 'title' from every registered tool's schema.

    Args:
        server: The FastMCP server instance.

    Returns:
        Number of tools whose schemas were stripped. Returns 0 if the
        FastMCP internals have changed and the operation cannot proceed.
    """
    try:
        tools = server._tool_manager._tools.values()
    except AttributeError:
        logger.debug(
            "strip_schema_titles: FastMCP internals changed — "
            "tool schemas remain unstripped (harmless)."
        )
        return 0

    stripped = 0
    for tool in tools:
        try:
            tool.parameters = _strip_titles(tool.parameters)
            stripped += 1
        except Exception as exc:
            logger.debug("Could not strip schema for tool: %s", exc)
    if stripped:
        logger.info("Stripped 'title' from %d tool schemas.", stripped)
    return stripped
