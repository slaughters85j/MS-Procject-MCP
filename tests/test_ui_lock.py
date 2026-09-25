"""
Concurrency and UI

Tests for ui_lock.py: UIMode, UILockState, get_ui_mode, set_ui_mode and
get_ui_state.
All tests mock COM — no live MS Project required.
"""

import logging

import pytest

from src import ui_lock
from src.ui_lock import (
    UILockState,
    UIMode,
    get_ui_mode,
    get_ui_state,
    set_ui_mode,
)
from tests.fakes import FakeApp

pytestmark = pytest.mark.usefixtures("reset_ui_state")


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
