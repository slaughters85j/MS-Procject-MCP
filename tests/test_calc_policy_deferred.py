"""
Calculate Policy

Tests for the calc_policy.deferred_calc context manager and its use
together with calculate_project.
All tests mock COM — no live MS Project required.
"""

import pytest
from unittest.mock import MagicMock
from src.calc_policy import (
    CalcState,
    deferred_calc,
    calculate_project,
)


# ---------------------------------------------------------------------------
# deferred_calc context manager
# ---------------------------------------------------------------------------

class TestDeferredCalc:
    def test_defers_when_automatic(self):
        """Should switch to MANUAL on entry, restore on exit."""
        app = MagicMock()
        # Track mode changes
        modes = [-1]  # start automatic

        def get_calc():
            return modes[-1]

        def set_calc(val):
            modes.append(val)

        type(app).Calculation = property(
            lambda self: get_calc(),
            lambda self, v: set_calc(v),
        )

        with deferred_calc(app) as state:
            assert state.was_deferred is True
            assert state.original_mode == -1
            # During context, mode should be MANUAL
            assert app.Calculation == 0

        # After context, mode should be restored to AUTOMATIC
        assert app.Calculation == -1

    def test_no_defer_when_already_manual(self):
        """Should not change mode if already manual."""
        app = MagicMock()
        app.Calculation = 0  # already manual

        with deferred_calc(app) as state:
            assert state.was_deferred is False
            assert state.mode == "manual"

    def test_yields_calc_state(self):
        app = MagicMock()
        app.Calculation = -1

        with deferred_calc(app) as state:
            assert isinstance(state, CalcState)
            assert state.mode == "automatic"
            assert state.mode_value == -1

    def test_restores_on_exception(self):
        """Mode must be restored even when body raises."""
        app = MagicMock()
        modes = [-1]
        type(app).Calculation = property(
            lambda self: modes[-1],
            lambda self, v: modes.append(v),
        )

        with pytest.raises(ValueError):
            with deferred_calc(app):
                assert app.Calculation == 0
                raise ValueError("boom")

        # Must restore to automatic despite the exception
        assert app.Calculation == -1

    def test_set_fails_on_entry_still_yields(self):
        """If switching to MANUAL fails, should still yield (with auto-calc)."""
        app = MagicMock()
        call_count = [0]

        def get_calc():
            return -1  # always automatic

        def set_calc(val):
            call_count[0] += 1
            raise Exception("COM write failed")

        type(app).Calculation = property(
            lambda self: get_calc(),
            lambda self, v: set_calc(v),
        )

        with deferred_calc(app) as state:
            # Should still yield, but was_deferred should be False
            assert state.was_deferred is False

    def test_restore_failure_raises(self):
        """If restoring calc mode fails on exit, must raise RuntimeError."""
        app = MagicMock()
        call_count = [0]

        def get_calc():
            return -1  # always reads as automatic

        def set_calc(val):
            call_count[0] += 1
            if call_count[0] == 1:
                # First set (to MANUAL) succeeds
                pass
            else:
                # Second set (restore) fails
                raise Exception("COM restore failed")

        type(app).Calculation = property(
            lambda self: get_calc(),
            lambda self, v: set_calc(v),
        )

        with pytest.raises(RuntimeError, match="could not restore"):
            with deferred_calc(app):
                pass  # body succeeds, but exit restore fails

    def test_calculate_project_name_failure_still_reports_success(self):
        """If Calculate succeeds but Name access fails, still report success."""
        app = MagicMock()
        project = MagicMock()
        app.ActiveProject = project  # already active: no activation needed
        app.CalculateProject.return_value = None
        type(project).Name = property(lambda self: (_ for _ in ()).throw(Exception("stale proxy")))
        result = calculate_project(app, project=project)
        assert result["recalculated"] is True
        assert result["error"] is None


# ---------------------------------------------------------------------------
# Integration: deferred_calc + calculate_project
# ---------------------------------------------------------------------------

class TestDeferredCalcIntegration:
    def test_batch_workflow(self):
        """Simulate the intended batch workflow."""
        app = MagicMock()
        modes = [-1]  # start automatic
        type(app).Calculation = property(
            lambda self: modes[-1],
            lambda self, v: modes.append(v),
        )

        # 1. Defer calc
        with deferred_calc(app) as state:
            assert state.was_deferred is True
            # 2. Do "batch writes" (simulated)

        # 3. Mode is restored to automatic
        assert app.Calculation == -1

        # 4. Explicit recalc
        result = calculate_project(app)
        assert result["recalculated"] is True

    def test_nested_deferred_calc_is_noop(self):
        """Inner deferred_calc should be a no-op if already manual."""
        app = MagicMock()
        modes = [-1]  # start automatic
        type(app).Calculation = property(
            lambda self: modes[-1],
            lambda self, v: modes.append(v),
        )

        with deferred_calc(app) as outer:
            assert outer.was_deferred is True
            assert app.Calculation == 0

            with deferred_calc(app) as inner:
                # Already manual, so no defer needed
                assert inner.was_deferred is False
                assert inner.mode == "manual"

            # Inner exit should NOT restore (was_deferred=False)
            assert app.Calculation == 0

        # Outer exit restores to automatic
        assert app.Calculation == -1
