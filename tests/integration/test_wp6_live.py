"""
WP-6 Live Integration Tests: Concurrency and UI

Tests UI lock modes against real MS Project.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.ui_lock import (
    UIMode,
    get_ui_mode,
    set_ui_mode,
    ui_lock,
    get_ui_state,
)


class TestUILock:
    """Real COM UI lock behavior."""

    def test_invisible_mode(self, temp_mpp):
        """Invisible mode: Visible=False."""
        app, proj, path = temp_mpp
        app.Visible = False
        mode = get_ui_mode(app)
        assert mode == UIMode.INVISIBLE

    def test_set_ui_mode_locked(self, temp_mpp):
        """Switch to LOCKED mode, read it back."""
        app, proj, path = temp_mpp
        app.Visible = True
        previous = set_ui_mode(app, UIMode.LOCKED)
        mode = get_ui_mode(app)
        assert mode == UIMode.LOCKED
        # Restore to invisible for clean teardown
        set_ui_mode(app, UIMode.INVISIBLE)

    def test_ui_lock_context_manager_in_locked_mode(self, temp_mpp):
        """ui_lock freezes ScreenUpdating in LOCKED mode."""
        app, proj, path = temp_mpp
        app.Visible = True
        set_ui_mode(app, UIMode.LOCKED)

        with ui_lock(app) as state:
            assert state.mode == "locked"
            # ScreenUpdating should be False inside the lock
            assert app.ScreenUpdating is False or not app.ScreenUpdating

            # Do some work inside the lock
            for t in proj.Tasks:
                if t is not None and not t.Summary:
                    t.Text1 = "Green"
                    break

        # ScreenUpdating should be restored after the lock
        assert app.ScreenUpdating is True or app.ScreenUpdating
        set_ui_mode(app, UIMode.INVISIBLE)

    def test_ui_lock_noop_in_invisible_mode(self, temp_mpp):
        """ui_lock is a no-op when Project is invisible."""
        app, proj, path = temp_mpp
        app.Visible = False

        with ui_lock(app) as state:
            assert state.mode == "invisible"
            # Should not have set ScreenUpdating at all
            assert state.screen_updating_was is None

    def test_get_ui_state_snapshot(self, temp_mpp):
        app, proj, path = temp_mpp
        state = get_ui_state(app)
        assert state.mode in ("invisible", "locked", "open")

    def test_ui_lock_restores_on_exception(self, temp_mpp):
        """ScreenUpdating is restored even when the body raises."""
        app, proj, path = temp_mpp
        app.Visible = True
        set_ui_mode(app, UIMode.LOCKED)

        with pytest.raises(ValueError):
            with ui_lock(app) as state:
                raise ValueError("Test exception")

        # ScreenUpdating should still be restored
        assert app.ScreenUpdating is True or app.ScreenUpdating
        set_ui_mode(app, UIMode.INVISIBLE)
