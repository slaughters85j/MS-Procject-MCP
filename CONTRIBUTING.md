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

Tests are organized by phase. Each test file creates a temporary project, runs assertions, and cleans up.

```bash
python test_phase2.py   # 10 tests
python test_phase3.py   # 15 tests
python test_phase4.py   # 21 tests
python test_phase5.py   # 11 tests
```

**Important:** MS Project must be running before you execute tests.

### Adding Tests

If you add a new tool, add corresponding tests. Follow the existing pattern:

```python
async def call(tool_name, **kwargs):
    result = await mcp.call_tool(tool_name, kwargs)
    contents = result[0] if isinstance(result, tuple) else result
    text = contents[0].text if contents else ""
    return json.loads(text) if text else {}
```

## Submitting Changes

1. Run all test phases and confirm they pass
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
