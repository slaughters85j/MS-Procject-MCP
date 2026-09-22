# Contributing to MS Project MCP Server

Thanks for your interest in contributing! Here's how to get started.

## Prerequisites

- Windows with Microsoft Project installed
- Python 3.10+
- `pip install mcp pywin32`

## Getting Started

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone git@github.com:<your-username>/MS-Procject-MCP.git
   cd MS-Procject-MCP
   ```
3. Create a branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development

`server.py` only wires the server together. Core tools live in `src/tools/`, one module per domain, each exposing a `register_<name>_tools(mcp)` function listed in `CORE_TOOL_MODULES` in `server.py`. Add a new tool to the module for its domain:

```python
import json

from ..com_helpers import get_app, get_proj


def register_example_tools(mcp):
    """Register the example tools on the FastMCP instance."""

    @mcp.tool()
    def your_tool(param: str) -> str:
        """Short description of what the tool does."""
        app  = get_app()
        proj = get_proj(app)

        # ... your logic ...

        return json.dumps({"status": "ok", ...}, indent=2)
```

Import safety helpers (`validate_safe_path`, `is_dry_run`, `com_call`, the response helpers) from `src/guards.py`, never from their own modules: `guards` supplies fallback stubs so the server still starts when one of them fails to load. A new tool also needs an entry in `src/annotations.py`.

### Conventions

- Use `get_app()` / `get_proj()` from `src/com_helpers.py` for COM access
- Use `_to_naive()` when comparing COM dates with `datetime.now()`
- Use `_fmt_date()` to format dates for JSON output
- Use `_parse_date()` to convert `YYYY-MM-DD` strings for COM input
- Return JSON strings from all tools
- Include docstrings — they become the tool description in MCP

## Testing

Unit tests live in `tests/`, named after the module they cover (`test_task_store.py`, `test_mpxj_reader.py`), and mock COM so they run on any platform:

```bash
pytest
```

Live tests live in `tests/integration/` and need Windows with MS Project installed; they skip automatically elsewhere. The tool-level scenario tests (`*_live.py`) each create a temporary project, drive the MCP tools, and clean up. Run them all with pytest, or one directly:

```bash
pytest tests/integration/ -v
python tests/integration/test_critical_path_live.py
```

### Adding Tests

If you add a new tool, add a unit test for it and extend the `*_live.py` scenario for its domain. The live scenarios call tools through this helper:

```python
async def call(tool_name, **kwargs):
    result = await mcp.call_tool(tool_name, kwargs)
    contents = result[0] if isinstance(result, tuple) else result
    text = contents[0].text if contents else ""
    return json.loads(text) if text else {}
```

## Submitting Changes

1. Run `pytest` (and `pytest tests/integration/` on Windows with MS Project) and confirm everything passes
2. Commit with a clear message describing what and why
3. Push to your fork and open a Pull Request
4. Describe the change, link any related issues, and note which tests cover it

## Reporting Issues

Open an issue with:
- What you expected vs what happened
- MS Project version (Help > About)
- Python version (`python --version`)
- Relevant error output

## Code of Conduct

Be respectful and constructive. We're all here to make MS Project automation better.
