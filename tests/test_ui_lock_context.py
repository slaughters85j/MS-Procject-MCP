"""
Concurrency and UI

Tests for the ui_lock.ui_lock context manager (freeze/restore, status bar,
nesting and COM failure handling).
All tests mock COM — no live MS Project required.
"""

import logging

import pytest

from src import ui_lock
from src.ui_lock import STATUS_MESSAGE, UIMode
from tests.fakes import FakeApp

pytestmark = pytest.mark.usefixtures("reset_ui_state")


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
