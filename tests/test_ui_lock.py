"""
Concurrency and UI

Tests for ui_lock.py and ui_tools.py.
All tests mock COM — no live MS Project required.
"""

import logging
from types import SimpleNamespace

import pytest

from src import ui_lock
from src.ui_lock import (
    STATUS_MESSAGE,
    UILockState,
    UIMode,
    get_ui_mode,
    get_ui_state,
    set_ui_mode,
)
from src.ui_tools import NO_SESSION_ERROR, register_ui_tools
from tests.fakes import FakeApp, FakeMCP


@pytest.fixture(autouse=True)
def reset_ui_state(monkeypatch):
    """Module-level UI state must not leak between tests."""
    monkeypatch.setattr(ui_lock, "_configured_mode", None)
    monkeypatch.setattr(ui_lock, "_active_lock", None)
    monkeypatch.setattr(ui_lock, "_last_restore_error", None)


# ---------------------------------------------------------------------------
# UIMode and UILockState
# ---------------------------------------------------------------------------

class TestUIMode:
    def test_values_round_trip(self):
        assert [m.value for m in UIMode] == ["invisible", "locked", "open"]
        assert all(UIMode(m.value) is m for m in UIMode)

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            UIMode("frozen")


class TestUILockState:
    def test_to_dict(self):
        state = UILockState(mode="locked", screen_updating_was=True,
                            locked_at=12.5, errors=["boom"])
        assert state.to_dict() == {
            "mode": "locked",
            "screen_updating_was": True,
            "locked_at": 12.5,
            "errors": ["boom"],
        }

    def test_defaults_not_shared_between_instances(self):
        a, b = UILockState(mode="open"), UILockState(mode="open")
        a.errors.append("x")
        assert (b.screen_updating_was, b.locked_at, b.errors) == (None, None, [])


# ---------------------------------------------------------------------------
# get_ui_mode
# ---------------------------------------------------------------------------

class TestGetUIMode:
    def test_invisible_when_not_visible(self):
        assert get_ui_mode(FakeApp(visible=False)) is UIMode.INVISIBLE

    def test_visible_defaults_to_locked(self):
        assert get_ui_mode(FakeApp(visible=True)) is UIMode.LOCKED

    def test_open_when_configured(self, monkeypatch):
        monkeypatch.setattr(ui_lock, "_configured_mode", UIMode.OPEN)
        assert get_ui_mode(FakeApp(visible=True)) is UIMode.OPEN

    def test_visible_window_overrides_configured_invisible(self, monkeypatch):
        """If something made the window visible again, protect it."""
        monkeypatch.setattr(ui_lock, "_configured_mode", UIMode.INVISIBLE)
        assert get_ui_mode(FakeApp(visible=True)) is UIMode.LOCKED

    def test_com_error_raises_readable_runtime_error(self, caplog):
        app = FakeApp()
        app.fail.add("Visible.get")
        with caplog.at_level(logging.ERROR, logger="src.ui_lock"):
            with pytest.raises(RuntimeError, match="FakeComError"):
                get_ui_mode(app)
        assert any("Application.Visible" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# set_ui_mode
# ---------------------------------------------------------------------------

class TestSetUIMode:
    def test_invisible_hides_window(self):
        app = FakeApp(visible=True)
        previous = set_ui_mode(app, UIMode.INVISIBLE)
        assert previous is UIMode.LOCKED
        assert app.Visible is False
        assert app.ScreenUpdating is True

    def test_locked_shows_window(self):
        app = FakeApp(visible=False)
        previous = set_ui_mode(app, UIMode.LOCKED)
        assert previous is UIMode.INVISIBLE
        assert app.Visible is True
        assert get_ui_mode(app) is UIMode.LOCKED

    def test_open_is_remembered(self):
        app = FakeApp(visible=False)
        set_ui_mode(app, UIMode.OPEN)
        assert get_ui_mode(app) is UIMode.OPEN

    def test_recovers_frozen_screen(self):
        app = FakeApp(visible=True, screen_updating=False)
        set_ui_mode(app, UIMode.LOCKED)
        assert app.ScreenUpdating is True

    def test_clears_last_restore_error(self, monkeypatch):
        monkeypatch.setattr(ui_lock, "_last_restore_error", "old failure")
        set_ui_mode(FakeApp(), UIMode.LOCKED)
        assert ui_lock._last_restore_error is None

    def test_refuses_inside_active_lock(self):
        app = FakeApp()
        with ui_lock.ui_lock(app):
            with pytest.raises(RuntimeError, match="UI lock is active"):
                set_ui_mode(app, UIMode.OPEN)

    def test_com_write_failure_raises_and_keeps_mode(self):
        app = FakeApp(visible=True)
        app.fail.add("Visible.set")
        with pytest.raises(RuntimeError, match="Setting UI mode to 'invisible'"):
            set_ui_mode(app, UIMode.INVISIBLE)
        assert ui_lock._configured_mode is None


# ---------------------------------------------------------------------------
# ui_lock context manager
# ---------------------------------------------------------------------------

class TestUILock:
    def test_freezes_and_restores_screen_updating(self):
        app = FakeApp(visible=True, screen_updating=True)
        with ui_lock.ui_lock(app) as state:
            assert app.ScreenUpdating is False
            assert state.screen_updating_was is True
            assert state.locked_at is not None
        assert app.ScreenUpdating is True
        assert state.errors == []

    def test_restores_saved_false_value(self):
        app = FakeApp(visible=True, screen_updating=False)
        with ui_lock.ui_lock(app):
            pass
        assert app.ScreenUpdating is False

    def test_sets_and_clears_status_bar(self):
        app = FakeApp()
        with ui_lock.ui_lock(app):
            assert app.StatusBar == STATUS_MESSAGE
        assert app.StatusBar is False

    def test_noop_when_invisible(self):
        app = FakeApp(visible=False)
        with ui_lock.ui_lock(app) as state:
            assert state.mode == "invisible"
        assert app.writes == []
        assert state.locked_at is None

    def test_noop_in_open_mode(self, monkeypatch):
        monkeypatch.setattr(ui_lock, "_configured_mode", UIMode.OPEN)
        app = FakeApp(visible=True)
        with ui_lock.ui_lock(app) as state:
            assert state.mode == "open"
        assert app.writes == []

    def test_restores_on_exception_and_propagates(self):
        app = FakeApp()
        with pytest.raises(ValueError, match="boom"):
            with ui_lock.ui_lock(app):
                raise ValueError("boom")
        assert app.ScreenUpdating is True
        assert app.StatusBar is False
        assert ui_lock._active_lock is None

    def test_restore_com_error_does_not_crash(self, caplog):
        app = FakeApp()
        with caplog.at_level(logging.ERROR, logger="src.ui_lock"):
            with ui_lock.ui_lock(app) as state:
                app.fail.add("ScreenUpdating.set")
        assert any("Restoring ScreenUpdating" in e for e in state.errors)
        assert "FakeComError" in state.errors[0]
        assert ui_lock._last_restore_error is not None
        assert any(r.levelno == logging.ERROR for r in caplog.records)

    def test_restore_error_survives_later_clean_restore(self):
        app = FakeApp()
        with ui_lock.ui_lock(app):
            app.fail.add("ScreenUpdating.set")
        app.fail.clear()
        with ui_lock.ui_lock(app) as state:
            pass
        assert state.errors == []
        assert "Restoring ScreenUpdating" in ui_lock._last_restore_error

    def test_restore_error_does_not_mask_body_exception(self):
        app = FakeApp()
        with pytest.raises(KeyError):
            with ui_lock.ui_lock(app):
                app.fail.add("ScreenUpdating.set")
                raise KeyError("body")
        assert ui_lock._last_restore_error is not None

    def test_status_bar_clear_failure_recorded(self):
        app = FakeApp()
        with ui_lock.ui_lock(app) as state:
            app.fail.add("StatusBar.set")
        assert app.ScreenUpdating is True
        assert any("Clearing StatusBar" in e for e in state.errors)

    def test_status_bar_set_failure_still_locks(self):
        app = FakeApp()
        app.fail.add("StatusBar.set")
        with ui_lock.ui_lock(app) as state:
            assert app.ScreenUpdating is False
        assert app.ScreenUpdating is True
        assert len(state.errors) == 1
        assert "Setting StatusBar" in state.errors[0]

    def test_visible_read_failure_skips_lock(self):
        app = FakeApp()
        app.fail.add("Visible.get")
        ran = []
        with ui_lock.ui_lock(app) as state:
            ran.append(True)
        assert ran == [True]
        assert state.mode == "unknown"
        assert "UI lock skipped" in state.errors[0]
        assert app.writes == []

    def test_freeze_failure_skips_lock(self):
        app = FakeApp()
        app.fail.add("ScreenUpdating.set")
        with ui_lock.ui_lock(app) as state:
            assert ui_lock._active_lock is None
        assert state.locked_at is None
        assert "freezing ScreenUpdating" in state.errors[0]
        assert app.writes == []

    def test_nested_lock_is_noop(self):
        app = FakeApp()
        with ui_lock.ui_lock(app) as outer:
            with ui_lock.ui_lock(app) as inner:
                assert inner is outer
            assert app.ScreenUpdating is False
        assert app.ScreenUpdating is True
        assert app.writes.count(("ScreenUpdating", False)) == 1

    def test_nested_body_exception_restores_once(self):
        app = FakeApp()
        with pytest.raises(ValueError):
            with ui_lock.ui_lock(app):
                with ui_lock.ui_lock(app):
                    raise ValueError("inner")
        assert app.writes.count(("ScreenUpdating", True)) == 1
        assert ui_lock._active_lock is None


# ---------------------------------------------------------------------------
# get_ui_state
# ---------------------------------------------------------------------------

class TestGetUIState:
    def test_idle_snapshot_does_not_write(self):
        app = FakeApp()
        assert get_ui_state(app).to_dict() == {"mode": "locked", "screen_updating_was": None,
                                              "locked_at": None, "errors": []}
        assert app.writes == []

    def test_reports_active_lock(self):
        app = FakeApp()
        with ui_lock.ui_lock(app) as lock:
            state = get_ui_state(app)
        assert state.screen_updating_was is True
        assert state.locked_at == lock.locked_at
        assert state.errors == []

    def test_reports_active_lock_errors(self):
        app = FakeApp()
        app.fail.add("StatusBar.set")
        with ui_lock.ui_lock(app):
            state = get_ui_state(app)
        assert any("Setting StatusBar" in e for e in state.errors)

    def test_reports_frozen_screen(self):
        state = get_ui_state(FakeApp(visible=True, screen_updating=False))
        assert any("frozen" in e for e in state.errors)

    def test_no_frozen_warning_when_invisible(self):
        state = get_ui_state(FakeApp(visible=False, screen_updating=False))
        assert state.errors == []

    def test_reports_last_restore_error(self, monkeypatch):
        monkeypatch.setattr(ui_lock, "_last_restore_error", "restore died")
        state = get_ui_state(FakeApp())
        assert any("restore died" in e for e in state.errors)

    def test_screen_updating_read_failure_recorded(self):
        app = FakeApp()
        app.fail.add("ScreenUpdating.get")
        state = get_ui_state(app)
        assert "FakeComError" in state.errors[0]

    def test_visible_read_failure_raises(self):
        app = FakeApp()
        app.fail.add("Visible.get")
        with pytest.raises(RuntimeError, match="Application.Visible"):
            get_ui_state(app)


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
