"""
Tests: Schema Size Reduction (src/schema_strip.py)

Tests that pydantic 'title' fields are stripped from tool schemas and
that the operation degrades gracefully when FastMCP internals change.
"""

from src.schema_strip import strip_schema_titles, _strip_titles


# ---------------------------------------------------------------------------
# _strip_titles (recursive)
# ---------------------------------------------------------------------------

class TestStripTitles:
    def test_removes_top_level_title(self):
        schema = {"title": "MyModel", "type": "object", "properties": {}}
        result = _strip_titles(schema)
        assert "title" not in result
        assert result["type"] == "object"

    def test_removes_nested_titles(self):
        schema = {
            "title": "Root",
            "properties": {
                "name": {"title": "Name", "type": "string"},
                "age": {"title": "Age", "type": "integer"},
            },
        }
        result = _strip_titles(schema)
        assert "title" not in result
        assert "title" not in result["properties"]["name"]
        assert "title" not in result["properties"]["age"]
        assert result["properties"]["name"]["type"] == "string"

    def test_handles_lists(self):
        schema = {"title": "X", "items": [{"title": "Y", "type": "string"}]}
        result = _strip_titles(schema)
        assert "title" not in result
        assert "title" not in result["items"][0]

    def test_preserves_non_title_keys(self):
        schema = {"type": "object", "description": "A thing", "required": ["x"]}
        result = _strip_titles(schema)
        assert result == schema

    def test_passthrough_scalars(self):
        assert _strip_titles(42) == 42
        assert _strip_titles("hello") == "hello"
        assert _strip_titles(None) is None


# ---------------------------------------------------------------------------
# strip_schema_titles (integration with fake FastMCP)
# ---------------------------------------------------------------------------

class FakeTool:
    """Minimal stand-in for FastMCP's internal tool object."""
    def __init__(self, parameters):
        self.parameters = parameters


class FakeToolManager:
    def __init__(self, tools):
        self._tools = tools


class FakeServer:
    def __init__(self, tools):
        self._tool_manager = FakeToolManager(tools)


class TestStripSchemaIntegration:
    def test_strips_from_multiple_tools(self):
        tools = {
            "get_tasks": FakeTool({"title": "GetTasks", "properties": {"id": {"title": "Id", "type": "int"}}}),
            "add_task": FakeTool({"title": "AddTask", "properties": {"name": {"title": "Name", "type": "string"}}}),
        }
        server = FakeServer(tools)
        count = strip_schema_titles(server)
        assert count == 2
        assert "title" not in tools["get_tasks"].parameters
        assert "title" not in tools["get_tasks"].parameters["properties"]["id"]
        assert "title" not in tools["add_task"].parameters

    def test_returns_zero_on_missing_internals(self):
        """Graceful fallback when FastMCP internals have changed."""
        class NoToolManager:
            pass
        count = strip_schema_titles(NoToolManager())
        assert count == 0

    def test_returns_zero_on_empty(self):
        server = FakeServer({})
        count = strip_schema_titles(server)
        assert count == 0

    def test_handles_tool_without_parameters_attr(self):
        """If a tool object lacks 'parameters', it's skipped, not crashed."""
        class BrokenTool:
            pass
        tools = {"broken": BrokenTool()}
        server = FakeServer(tools)
        count = strip_schema_titles(server)
        # BrokenTool has no .parameters, so strip fails for it
        assert count == 0
