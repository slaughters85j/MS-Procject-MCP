"""
Integration Tests: server.py wiring of the WP-1 to WP-6 tools

Loads server.py with FakeMCP in place of FastMCP, so neither the mcp package
nor pywin32 is required. Checks that the legacy and hardening tools register
side by side and that load failures surface readably.
"""

import importlib.util
import inspect
import json
import logging
import os
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src import task_store
from tests.fakes import FakeMCP

SERVER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server.py"
)
LEGACY_TOOL_COUNT = 99
SPRINT2_TOOLS = {"get_tool_guide"}                                       # Sprint 2
WP_TOOLS = {
    "session_attach", "session_detach", "session_info",                  # WP-1
    "get_project_identity", "validate_project", "switch_project_confirmed",
    "list_open_projects",                                                # WP-2
    "get_calculation_mode", "set_calculation_mode", "calculate_now",     # WP-4
    "resolve_task", "resolve_resource", "invalidate_store", "store_stats",  # WP-5
    "get_ui_mode", "set_ui_mode", "get_ui_state",                        # WP-6
    "bulk_update", "bulk_status",                                        # WP-7
}


@pytest.fixture
def server(monkeypatch):
    """Import server.py fresh, with FakeMCP standing in for mcp.server.fastmcp.FastMCP."""
    fastmcp = types.ModuleType("mcp.server.fastmcp")
    fastmcp.FastMCP = FakeMCP
    for name in ("mcp", "mcp.server"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp)
    # server.py calls init_store(); restore the singleton so other suites are unaffected.
    monkeypatch.setattr(task_store, "_store", task_store._store)
    spec = importlib.util.spec_from_file_location("server_under_test", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestRegistration:
    def test_legacy_and_wp_tools_register_side_by_side(self, server):
        tools = server.mcp.tools
        assert WP_TOOLS <= set(tools)
        assert len(tools) == LEGACY_TOOL_COUNT + len(WP_TOOLS) + len(SPRINT2_TOOLS)
        assert server.mcp.duplicates == []
        assert server.WP_LOAD_ERRORS == []

    def test_switch_tools_keep_separate_signatures(self, server):
        tools = server.mcp.tools
        assert list(inspect.signature(tools["switch_project"]).parameters) == ["name_or_index"]
        assert "confirm" in inspect.signature(tools["switch_project_confirmed"]).parameters

    def test_store_is_initialized(self, server):
        assert task_store.get_store() is not None

    def test_failed_module_is_logged_and_others_load(self, server, monkeypatch, caplog):
        monkeypatch.setattr(server, "mcp", FakeMCP())
        monkeypatch.setattr(server, "WP_LOAD_ERRORS", [])
        monkeypatch.setattr(server, "WP_TOOL_MODULES",
                            (("src.missing_module", "register_x"),) + server.WP_TOOL_MODULES)
        with caplog.at_level(logging.ERROR):
            server._register_wp_tools()
        assert len(server.WP_LOAD_ERRORS) == 1
        assert "src.missing_module" in server.WP_LOAD_ERRORS[0]
        assert "ModuleNotFoundError" in server.WP_LOAD_ERRORS[0]
        assert any("src.missing_module" in r.getMessage() for r in caplog.records)
        assert WP_TOOLS <= set(server.mcp.tools)


class TestToolGuideAccuracy:
    def test_tool_guide_names_are_subset_of_registered_tools(self, server):
        """Every tool name in _TOOL_GUIDE must be a real registered tool."""
        from src.tool_guide import _TOOL_GUIDE
        guide_names = set()
        for category_tools in _TOOL_GUIDE["tool_categories"].values():
            guide_names.update(category_tools)
        for pair in _TOOL_GUIDE["bulk_pairs"].values():
            guide_names.add(pair["single"])
            guide_names.add(pair["bulk"])
        registered = set(server.mcp.tools.keys())
        missing = guide_names - registered
        assert missing == set(), f"Tool guide references non-existent tools: {sorted(missing)}"


class TestHealthCheck:
    def test_reports_load_errors(self, server, monkeypatch):
        monkeypatch.setattr(server, "_find_app", lambda: None)
        monkeypatch.setattr(server, "WP_LOAD_ERRORS", ["src.ui_tools failed to load (X): y"])
        result = json.loads(server.mcp.tools["health_check"]())
        assert result["status"] == "disconnected"
        assert result["hardening_tool_errors"] == ["src.ui_tools failed to load (X): y"]

    def test_no_error_key_when_all_loaded(self, server, monkeypatch):
        monkeypatch.setattr(server, "_find_app", lambda: None)
        result = json.loads(server.mcp.tools["health_check"]())
        assert "hardening_tool_errors" not in result


class TestConnectHelpers:
    def test_find_app_prefers_attached_session(self, server, monkeypatch):
        app = object()
        session = SimpleNamespace(is_attached=True, app=app)
        monkeypatch.setattr(server, "get_session", lambda: session)
        assert server._find_app() is app

    def test_launch_app_goes_through_session(self, server, monkeypatch):
        app = SimpleNamespace(DisplayAlerts=True)
        session = MagicMock()
        session.attach.return_value = SimpleNamespace(app=app)
        monkeypatch.setattr(server, "get_session", lambda: session)
        assert server._launch_app() is app
        session.attach.assert_called_once()
        assert app.DisplayAlerts is False
        assert not hasattr(app, "Visible")  # the session owns visibility

    def test_get_app_not_running_message(self, server, monkeypatch):
        monkeypatch.setattr(server, "_find_app", lambda: None)
        with pytest.raises(RuntimeError, match="Could not attach to MS Project"):
            server.get_app()

    def test_open_project_launches_when_not_running(self, server, monkeypatch):
        # Ensure safe_root doesn't interfere (may leak from other test modules)
        monkeypatch.delenv("MSPROJECT_SAFE_ROOT", raising=False)
        from src.safe_path import reload_safe_root
        reload_safe_root()

        app = MagicMock()
        app.ActiveProject.configure_mock(Name="a.mpp", FullName="C:\\a.mpp",
                                         ProjectStart="2026-01-01", ProjectFinish="2026-02-01")
        app.ActiveProject.Tasks.Count = 3
        monkeypatch.setattr(server, "_find_app", lambda: None)
        monkeypatch.setattr(server, "_launch_app", lambda: app)
        result = json.loads(server.mcp.tools["open_project"]("C:\\a.mpp"))
        app.FileOpen.assert_called_once_with("C:\\a.mpp")
        assert result["status"] == "opened"

    def test_session_project_source_needs_session(self, server, monkeypatch):
        monkeypatch.setattr(server, "get_session", None)
        with pytest.raises(RuntimeError, match="WP-1 session is unavailable"):
            server._session_active_project()
