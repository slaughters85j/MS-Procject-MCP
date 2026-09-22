"""
Unit tests for the mpxj MCP tools: registration, path confinement, response management,
error responses, and their annotations and tool guide entries.
"""

import json
import os
from unittest.mock import MagicMock

import pytest

from src.mpxj_jvm import MpxjParseError
from src.response import paginate, strip_empty, format_response


class TestSafePathEnforcement:
    def test_safe_path_rejects_outside_root(self, tmp_mpp, monkeypatch):
        """Verify safe_path raises ValueError for paths outside MSPROJECT_SAFE_ROOT."""
        from src import safe_path

        # Set safe root to a directory that doesn't contain tmp_mpp
        monkeypatch.setenv("MSPROJECT_SAFE_ROOT", "/some/other/directory")
        safe_path.reload_safe_root()

        try:
            with pytest.raises(ValueError, match="Path confinement violation"):
                safe_path.validate_safe_path(tmp_mpp)
        finally:
            # Reset
            monkeypatch.delenv("MSPROJECT_SAFE_ROOT", raising=False)
            safe_path.reload_safe_root()

    def test_safe_path_accepts_within_root(self, tmp_mpp, monkeypatch):
        """Verify safe_path accepts paths within MSPROJECT_SAFE_ROOT."""
        from src import safe_path

        parent_dir = os.path.dirname(tmp_mpp)
        monkeypatch.setenv("MSPROJECT_SAFE_ROOT", parent_dir)
        safe_path.reload_safe_root()

        try:
            result = safe_path.validate_safe_path(tmp_mpp)
            assert os.path.isabs(result)
        finally:
            monkeypatch.delenv("MSPROJECT_SAFE_ROOT", raising=False)
            safe_path.reload_safe_root()


class TestResponseManagement:
    def test_paginate_tasks(self):
        tasks = [{"unique_id": i, "name": f"Task {i}"} for i in range(50)]
        page, meta = paginate(tasks, offset=0, limit=10)
        assert len(page) == 10
        assert meta["total"] == 50
        assert meta["truncated"] is True
        assert meta["next_offset"] == 10

    def test_strip_empty_removes_none(self):
        task = {"unique_id": 1, "name": "T1", "notes": None, "cost": 0}
        result = strip_empty(task)
        assert "notes" not in result
        assert "cost" not in result  # zero is dropped for non-meaningful fields
        assert result["unique_id"] == 1

    def test_strip_empty_keeps_identity(self):
        task = {"unique_id": 0, "name": "", "id": 0}
        result = strip_empty(task)
        assert "unique_id" in result
        assert "name" in result
        assert "id" in result

    def test_format_response_compact_large(self):
        large = {"data": ["x" * 100] * 100}
        result = format_response(large)
        assert "\n" not in result  # compact format

    def test_format_response_indented_small(self):
        small = {"count": 1}
        result = format_response(small)
        assert "\n" in result  # indented format


class TestToolRegistration:
    def test_register_mpxj_tools(self):
        """Verify that register_mpxj_tools adds 5 tools to a mock FastMCP."""
        mock_mcp = MagicMock()
        registered_tools = {}

        def mock_tool_decorator():
            def decorator(func):
                registered_tools[func.__name__] = func
                return func
            return decorator

        mock_mcp.tool = mock_tool_decorator

        from src.mpxj_tools import register_mpxj_tools
        register_mpxj_tools(mock_mcp)

        expected = {
            "mpxj_read_tasks",
            "mpxj_read_resources",
            "mpxj_read_project_info",
            "mpxj_read_assignments",
            "mpxj_read_calendars",
        }
        assert set(registered_tools.keys()) == expected

    def test_tool_descriptions_mention_saved(self):
        """Verify each tool's docstring mentions SAVED file."""
        mock_mcp = MagicMock()
        registered_tools = {}

        def mock_tool_decorator():
            def decorator(func):
                registered_tools[func.__name__] = func
                return func
            return decorator

        mock_mcp.tool = mock_tool_decorator

        from src.mpxj_tools import register_mpxj_tools
        register_mpxj_tools(mock_mcp)

        for name, func in registered_tools.items():
            assert "SAVED" in func.__doc__, f"{name} docstring must mention SAVED"


class TestToolErrorResponses:
    def test_mpxj_file_error_response(self):
        """Verify MpxjFileError produces a proper JSON error response."""
        from src.mpxj_reader import MpxjFileError
        error = MpxjFileError("File not found: test.mpp")
        response = format_response({
            "error": True,
            "error_type": "MpxjFileError",
            "message": str(error),
        })
        parsed = json.loads(response)
        assert parsed["error"] is True
        assert parsed["error_type"] == "MpxjFileError"
        assert "File not found" in parsed["message"]

    def test_mpxj_parse_error_response(self):
        error = MpxjParseError("Failed to parse: corrupt file")
        response = format_response({
            "error": True,
            "error_type": "MpxjParseError",
            "message": str(error),
        })
        parsed = json.loads(response)
        assert parsed["error"] is True
        assert "corrupt" in parsed["message"]

    def test_value_error_from_safe_path(self):
        error = ValueError("Path confinement violation")
        response = format_response({
            "error": True,
            "error_type": "ValueError",
            "message": str(error),
        })
        parsed = json.loads(response)
        assert "confinement" in parsed["message"]


class TestAnnotationsIntegration:
    def test_mpxj_tools_in_annotations(self):
        from src.annotations import TOOL_ANNOTATIONS

        mpxj_tools = [
            "mpxj_read_tasks",
            "mpxj_read_resources",
            "mpxj_read_project_info",
            "mpxj_read_assignments",
            "mpxj_read_calendars",
        ]

        for tool_name in mpxj_tools:
            assert tool_name in TOOL_ANNOTATIONS, f"{tool_name} missing from TOOL_ANNOTATIONS"
            ann = TOOL_ANNOTATIONS[tool_name]
            assert ann["readOnlyHint"] is True, f"{tool_name} must be readOnlyHint=True"
            assert ann["destructiveHint"] is False, f"{tool_name} must be destructiveHint=False"
            assert ann["idempotentHint"] is True, f"{tool_name} must be idempotentHint=True"


class TestToolGuideIntegration:
    def test_mpxj_category_in_tool_guide(self):
        from src.tool_guide import _TOOL_GUIDE

        assert "mpxj_fast_read" in _TOOL_GUIDE["tool_categories"]
        mpxj_tools = _TOOL_GUIDE["tool_categories"]["mpxj_fast_read"]
        assert "mpxj_read_tasks" in mpxj_tools
        assert "mpxj_read_resources" in mpxj_tools
        assert "mpxj_read_project_info" in mpxj_tools
        assert "mpxj_read_assignments" in mpxj_tools
        assert "mpxj_read_calendars" in mpxj_tools

    def test_server_instructions_mention_mpxj(self):
        from src.tool_guide import SERVER_INSTRUCTIONS

        assert "mpxj" in SERVER_INSTRUCTIONS.lower()
        assert "SAVED" in SERVER_INSTRUCTIONS
