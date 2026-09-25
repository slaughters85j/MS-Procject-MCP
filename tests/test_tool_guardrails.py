"""
Tests for src.tool_guardrails on a real FastMCP instance with fake tools (no COM).
"""

import asyncio
import json

import pytest
from mcp.server.fastmcp import FastMCP

from src import tool_guardrails
from src.annotations import TOOL_ANNOTATIONS


@pytest.fixture
def server(monkeypatch):
    """A FastMCP with one read-only and several mutating tools, guarded like the real server."""
    calls = []
    mcp = FastMCP("test")

    @mcp.tool()
    def get_task(unique_id: int) -> str:
        return json.dumps({"unique_id": unique_id})

    @mcp.tool()
    def update_task(unique_id: int, name: str = "") -> str:
        calls.append(("update_task", unique_id, name))
        return json.dumps({"status": "updated"})

    @mcp.tool()
    def delete_task(unique_id: int) -> str:
        if unique_id == 0:
            return json.dumps({"error": "Task UniqueID 0 not found."})
        raise ValueError("boom")

    @mcp.tool()
    def validate_project(project_id: str) -> dict:
        return {"valid": False, "error": "mismatch"}

    monkeypatch.setitem(TOOL_ANNOTATIONS, "validate_project", {"readOnlyHint": True})
    monkeypatch.setattr(tool_guardrails, "_app_or_none", lambda: None)
    monkeypatch.setattr("src.guards.get_session", None)
    tool_guardrails.apply_guardrails(mcp)
    return mcp, calls


def _call(mcp, name, args):
    result = asyncio.run(mcp.call_tool(name, args))
    if hasattr(result, "isError"):
        return result.isError, json.loads(result.content[0].text)
    content = result[0] if isinstance(result, tuple) else result
    return False, json.loads(content[0].text)


class TestStrictArguments:
    def test_unknown_argument_is_rejected(self, server):
        mcp, calls = server
        is_error, body = _call(mcp, "update_task", {"unique_id": 1, "duration": "2d"})
        assert is_error and body["error_type"] == "invalid_arguments"
        assert calls == []

    def test_schema_forbids_additional_properties(self, server):
        mcp, _ = server
        tool = mcp._tool_manager._tools["update_task"]
        assert tool.parameters["additionalProperties"] is False
        assert "project_id" in tool.parameters["properties"]
        assert "project_id" not in mcp._tool_manager._tools["get_task"].parameters["properties"]


class TestErrorContract:
    def test_error_json_result_becomes_is_error(self, server):
        mcp, _ = server
        is_error, body = _call(mcp, "delete_task", {"unique_id": 0})
        assert is_error and body["error"] == "Task UniqueID 0 not found."

    def test_exception_becomes_is_error_json(self, server):
        mcp, _ = server
        is_error, body = _call(mcp, "delete_task", {"unique_id": 5})
        assert is_error and body == {"error": "boom", "error_type": "invalid_input"}

    def test_validation_answer_is_not_an_error(self, server):
        mcp, _ = server
        is_error, body = _call(mcp, "validate_project", {"project_id": "x"})
        assert not is_error and body["valid"] is False

    def test_mpxj_error_shape_is_normalised(self):
        payload = tool_guardrails._error_payload({"error": True, "error_type": "E", "message": "m"}, "mpxj_read_tasks")
        assert payload["error"] == "m" and "message" not in payload


class TestDryRun:
    @pytest.mark.parametrize("value", ["1", "true", "True", "YES"])
    def test_mutating_tool_is_blocked(self, server, monkeypatch, value):
        mcp, calls = server
        monkeypatch.setenv("MSPROJECT_DRY_RUN", value)
        is_error, body = _call(mcp, "update_task", {"unique_id": 1, "name": "x"})
        assert not is_error and body["status"] == "dry-run"
        assert calls == []

    def test_read_only_tool_still_runs(self, server, monkeypatch):
        mcp, _ = server
        monkeypatch.setenv("MSPROJECT_DRY_RUN", "1")
        _, body = _call(mcp, "get_task", {"unique_id": 7})
        assert body == {"unique_id": 7}
