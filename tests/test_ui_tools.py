"""
Concurrency and UI

Tests for the MCP tools registered by ui_tools.py.
All tests mock COM — no live MS Project required.
"""

from types import SimpleNamespace

import pytest

from src import ui_lock
from src.ui_tools import NO_SESSION_ERROR, register_ui_tools
from tests.fakes import FakeApp, FakeMCP

pytestmark = pytest.mark.usefixtures("reset_ui_state")


# ---------------------------------------------------------------------------
# MCP tools (ui_tools.py)
# ---------------------------------------------------------------------------

@pytest.fixture
def tools_with_app(monkeypatch):
    """Register the UI tools against a fake session holding a FakeApp."""
    app = FakeApp()
    session = SimpleNamespace(_app=app)
    monkeypatch.setattr("src.project_session.get_session", lambda: session)
    mcp = FakeMCP()
    register_ui_tools(mcp)
    return mcp.tools, app, session


class TestUITools:
    def test_registers_three_tools(self, tools_with_app):
        tools, _, _ = tools_with_app
        assert set(tools) == {"get_ui_mode", "set_ui_mode", "get_ui_state"}

    def test_no_session_returns_error(self, tools_with_app):
        tools, _, session = tools_with_app
        session._app = None
        for name, kwargs in (("get_ui_mode", {}), ("get_ui_state", {}),
                             ("set_ui_mode", {"mode": "open"})):
            assert tools[name](**kwargs) == {"error": NO_SESSION_ERROR}

    def test_get_ui_mode_and_state(self, tools_with_app):
        tools, _, _ = tools_with_app
        assert tools["get_ui_mode"]() == {"mode": "locked", "lock_active": False,
                                          "errors": []}
        assert tools["get_ui_state"]()["mode"] == "locked"

    def test_get_ui_mode_surfaces_restore_error(self, tools_with_app, monkeypatch):
        tools, _, _ = tools_with_app
        monkeypatch.setattr(ui_lock, "_last_restore_error", "restore died")
        assert any("restore died" in e for e in tools["get_ui_mode"]()["errors"])

    def test_set_ui_mode_normalizes_input(self, tools_with_app):
        tools, app, _ = tools_with_app
        result = tools["set_ui_mode"](mode="  Invisible ")
        assert result == {"previous_mode": "locked", "new_mode": "invisible",
                          "changed": True}
        assert app.Visible is False

    def test_set_ui_mode_invalid(self, tools_with_app):
        tools, app, _ = tools_with_app
        for bad in ("frozen", None):
            result = tools["set_ui_mode"](mode=bad)
            assert "invisible, locked, open" in result["error"]
        assert app.writes == []

    def test_set_ui_mode_inside_lock_returns_error(self, tools_with_app):
        tools, app, _ = tools_with_app
        with ui_lock.ui_lock(app):
            result = tools["set_ui_mode"](mode="open")
        assert "UI lock is active" in result["error"]

    def test_set_ui_mode_com_failure(self, tools_with_app):
        tools, app, _ = tools_with_app
        app.fail.add("ScreenUpdating.set")
        result = tools["set_ui_mode"](mode="open")
        assert "FakeComError" in result["error"]

    def test_com_failure_surfaces_as_error_key(self, tools_with_app):
        tools, app, _ = tools_with_app
        app.fail.add("Visible.get")
        assert "Application.Visible" in tools["get_ui_mode"]()["error"]
        assert "Application.Visible" in tools["get_ui_state"]()["error"]
