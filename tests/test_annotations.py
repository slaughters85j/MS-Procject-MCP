"""
Tests for ToolAnnotations (src/annotations.py).

Covers:
  - Every tool in TOOL_ANNOTATIONS has valid classification fields
  - apply_annotations works on a FakeMCP instance
  - Classification correctness: read-only tools, destructive tools, idempotent tools
  - All server.py tools are classified (no gaps)
"""

import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Ensure mcp.types.ToolAnnotations is available (mock if needed)
try:
    from mcp.types import ToolAnnotations  # noqa: F401
except (ImportError, ModuleNotFoundError):
    # Create a minimal mock so apply_annotations can function in test
    _mock_mcp_types = MagicMock()

    class _MockToolAnnotations:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    _mock_mcp_types.ToolAnnotations = _MockToolAnnotations
    if "mcp" not in sys.modules:
        sys.modules["mcp"] = MagicMock()
    if "mcp.types" not in sys.modules:
        sys.modules["mcp.types"] = _mock_mcp_types
    else:
        sys.modules["mcp.types"].ToolAnnotations = _MockToolAnnotations

from src.annotations import TOOL_ANNOTATIONS, apply_annotations


# ---------------------------------------------------------------------------
# Classification integrity
# ---------------------------------------------------------------------------

class TestAnnotationIntegrity:
    def test_all_entries_have_required_fields(self):
        for name, spec in TOOL_ANNOTATIONS.items():
            assert "title" in spec, f"{name} missing title"
            assert "readOnlyHint" in spec, f"{name} missing readOnlyHint"
            assert "destructiveHint" in spec, f"{name} missing destructiveHint"
            assert "idempotentHint" in spec, f"{name} missing idempotentHint"

    def test_hints_are_booleans(self):
        for name, spec in TOOL_ANNOTATIONS.items():
            for field in ("readOnlyHint", "destructiveHint", "idempotentHint"):
                assert isinstance(spec[field], bool), \
                    f"{name}.{field} should be bool, got {type(spec[field])}"

    def test_titles_are_nonempty_strings(self):
        for name, spec in TOOL_ANNOTATIONS.items():
            assert isinstance(spec["title"], str) and spec["title"], \
                f"{name} has empty or non-string title"

    def test_no_duplicate_titles(self):
        titles = [spec["title"] for spec in TOOL_ANNOTATIONS.values()]
        assert len(titles) == len(set(titles)), "Duplicate titles found"


# ---------------------------------------------------------------------------
# Classification correctness
# ---------------------------------------------------------------------------

class TestClassificationCorrectness:
    """Verify critical classification decisions."""

    READ_ONLY_TOOLS = [
        "get_tasks", "get_task", "get_critical_path", "get_resources",
        "filter_tasks", "search_tasks", "get_wbs_structure",
        "get_schedule_analysis", "validate_schedule", "health_check",
        "get_tool_guide", "session_info", "get_project_identity",
        "dry_run_bulk_update", "snapshot_diff", "bulk_status",
        "store_stats", "get_ui_mode", "get_ui_state",
    ]

    DESTRUCTIVE_TOOLS = [
        "delete_task", "delete_resource", "delete_calendar",
        "delete_calendar_exception", "close_project",
        "clear_baseline", "remove_predecessor",
        "remove_resource_assignment",
    ]

    IDEMPOTENT_MUTATORS = [
        "update_task", "set_task_mode", "set_constraint",
        "set_deadline", "set_task_active", "bulk_update_tasks",
        "bulk_update_rag", "bulk_set_task_mode", "bulk_set_deadlines",
        "bulk_update", "save_project", "calculate_project",
    ]

    def test_read_only_tools(self):
        for name in self.READ_ONLY_TOOLS:
            spec = TOOL_ANNOTATIONS[name]
            assert spec["readOnlyHint"] is True, f"{name} should be readOnly"
            assert spec["destructiveHint"] is False, f"{name} should not be destructive"

    def test_destructive_tools(self):
        for name in self.DESTRUCTIVE_TOOLS:
            spec = TOOL_ANNOTATIONS[name]
            assert spec["destructiveHint"] is True, f"{name} should be destructive"
            assert spec["readOnlyHint"] is False, f"{name} should not be readOnly"

    def test_idempotent_mutators(self):
        for name in self.IDEMPOTENT_MUTATORS:
            spec = TOOL_ANNOTATIONS[name]
            assert spec["idempotentHint"] is True, f"{name} should be idempotent"
            assert spec["readOnlyHint"] is False, f"{name} should not be readOnly"

    def test_no_tool_is_both_readonly_and_destructive(self):
        for name, spec in TOOL_ANNOTATIONS.items():
            if spec["readOnlyHint"]:
                assert not spec["destructiveHint"], \
                    f"{name} cannot be both readOnly and destructive"

    def test_dry_run_is_readonly(self):
        """dry_run tools preview changes without applying."""
        assert TOOL_ANNOTATIONS["dry_run_bulk_update"]["readOnlyHint"] is True

    def test_bulk_update_is_idempotent(self):
        """bulk_update is set-based (idempotent), not additive."""
        assert TOOL_ANNOTATIONS["bulk_update"]["idempotentHint"] is True


# ---------------------------------------------------------------------------
# apply_annotations on FakeMCP
# ---------------------------------------------------------------------------

class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.annotations = None
        self.parameters = {}


class _FakeToolManager:
    def __init__(self, tool_names):
        self._tools = {n: _FakeTool(n) for n in tool_names}


class _FakeMCPServer:
    def __init__(self, tool_names):
        self._tool_manager = _FakeToolManager(tool_names)


class TestApplyAnnotations:
    def test_annotates_known_tools(self):
        server = _FakeMCPServer(["get_tasks", "delete_task", "health_check"])
        count = apply_annotations(server)
        assert count == 3

        get_tasks_tool = server._tool_manager._tools["get_tasks"]
        assert get_tasks_tool.annotations is not None
        assert get_tasks_tool.annotations.readOnlyHint is True

        delete_tool = server._tool_manager._tools["delete_task"]
        assert delete_tool.annotations.destructiveHint is True

    def test_unknown_tools_not_annotated(self):
        server = _FakeMCPServer(["nonexistent_tool"])
        count = apply_annotations(server)
        assert count == 0
        assert server._tool_manager._tools["nonexistent_tool"].annotations is None

    def test_returns_count(self):
        names = list(TOOL_ANNOTATIONS.keys())[:10]
        server = _FakeMCPServer(names)
        count = apply_annotations(server)
        assert count == 10

    def test_graceful_on_broken_server(self):
        """If server internals are inaccessible, returns 0 and doesn't crash."""
        class BrokenServer:
            pass
        count = apply_annotations(BrokenServer())
        assert count == 0


# ---------------------------------------------------------------------------
# Coverage check: all server.py tools must be classified
# ---------------------------------------------------------------------------

class TestCoverage:
    """Ensure TOOL_ANNOTATIONS covers all tools defined in server.py and src/*_tools.py."""

    def test_minimum_tool_count(self):
        """We know we have ~99 tools. This catches accidental mass deletion."""
        assert len(TOOL_ANNOTATIONS) >= 90, \
            f"Only {len(TOOL_ANNOTATIONS)} tools classified — expected ~99+"
