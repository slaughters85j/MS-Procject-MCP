"""
Shared helper for the scenario tests that call tools through FastMCP.call_tool.

call_tool returns content blocks for a normal result, or a CallToolResult (isError=true,
JSON body {"error", "error_type"}) when the guardrail layer reports a failure.
"""


def tool_text(result):
    """The text of a call_tool result, whichever shape it has."""
    if hasattr(result, "content"):
        return result.content[0].text if result.content else ""
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, list):
        item = result[0] if result else None
        return getattr(item, "text", str(item) if item is not None else "")
    return getattr(result, "text", str(result))
