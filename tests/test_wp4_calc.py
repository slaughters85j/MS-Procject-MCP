"""
WP-4 Tests: Calculate Policy

Tests for calc_policy.py and calc_tools.py.
All tests mock COM — no live MS Project required.
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from src.calc_policy import (
    CalcMode,
    CalcState,
    get_calc_mode,
    set_calc_mode,
    deferred_calc,
    calculate_project,
    get_calc_state,
)


# ---------------------------------------------------------------------------
# CalcMode enum
# ---------------------------------------------------------------------------

class TestCalcMode:
    def test_automatic_value(self):
        assert CalcMode.AUTOMATIC == 0

    def test_manual_value(self):
        assert CalcMode.MANUAL == 1

    def test_from_int(self):
        assert CalcMode(0) == CalcMode.AUTOMATIC
        assert CalcMode(1) == CalcMode.MANUAL

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            CalcMode(99)

    def test_int_cast(self):
        assert int(CalcMode.AUTOMATIC) == 0
        assert int(CalcMode.MANUAL) == 1


# ---------------------------------------------------------------------------
# CalcState dataclass
# ---------------------------------------------------------------------------

class TestCalcState:
    def test_to_dict(self):
        state = CalcState(
            mode="automatic",
            mode_value=0,
            was_deferred=True,
            original_mode=0,
        )
        d = state.to_dict()
        assert d["mode"] == "automatic"
        assert d["mode_value"] == 0
        assert d["was_deferred"] is True
        assert d["original_mode"] == 0

    def test_defaults(self):
        state = CalcState(mode="manual", mode_value=1, was_deferred=False)
        assert state.original_mode is None


# ---------------------------------------------------------------------------
# get_calc_mode
# ---------------------------------------------------------------------------

class TestGetCalcMode:
    def test_reads_automatic(self):
        app = MagicMock()
        app.Calculation = 0
        assert get_calc_mode(app) == CalcMode.AUTOMATIC

    def test_reads_manual(self):
        app = MagicMock()
        app.Calculation = 1
        assert get_calc_mode(app) == CalcMode.MANUAL

    def test_invalid_value_returns_automatic(self):
        """Unknown COM value should default to AUTOMATIC safely."""
        app = MagicMock()
        app.Calculation = 42
        result = get_calc_mode(app)
        assert result == CalcMode.AUTOMATIC

    def test_attribute_error_returns_automatic(self):
        """Missing Calculation attribute should default safely."""
        app = MagicMock(spec=[])  # no attributes
        result = get_calc_mode(app)
        assert result == CalcMode.AUTOMATIC


# ---------------------------------------------------------------------------
# set_calc_mode
# ---------------------------------------------------------------------------

class TestSetCalcMode:
    def test_sets_mode_and_returns_previous(self):
        app = MagicMock()
        app.Calculation = 0  # currently automatic
        previous = set_calc_mode(app, CalcMode.MANUAL)
        assert previous == CalcMode.AUTOMATIC
        assert app.Calculation == 1

    def test_set_same_mode(self):
        app = MagicMock()
        app.Calculation = 1
        previous = set_calc_mode(app, CalcMode.MANUAL)
        assert previous == CalcMode.MANUAL

    def test_com_error_raises_runtime(self):
        app = MagicMock()
        app.Calculation = 0
        # Make the setter raise
        type(app).Calculation = PropertyMock(
            return_value=0,
            side_effect=[0, Exception("COM error")]
        )
        with pytest.raises(RuntimeError, match="Could not set"):
            set_calc_mode(app, CalcMode.MANUAL)


# ---------------------------------------------------------------------------
# deferred_calc context manager
# ---------------------------------------------------------------------------

class TestDeferredCalc:
    def test_defers_when_automatic(self):
        """Should switch to MANUAL on entry, restore on exit."""
        app = MagicMock()
        # Track mode changes
        modes = [0]  # start automatic

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
            assert state.original_mode == 0
            # During context, mode should be MANUAL
            assert app.Calculation == 1

        # After context, mode should be restored to AUTOMATIC
        assert app.Calculation == 0

    def test_no_defer_when_already_manual(self):
        """Should not change mode if already manual."""
        app = MagicMock()
        app.Calculation = 1  # already manual

        with deferred_calc(app) as state:
            assert state.was_deferred is False
            assert state.mode == "manual"

    def test_yields_calc_state(self):
        app = MagicMock()
        app.Calculation = 0

        with deferred_calc(app) as state:
            assert isinstance(state, CalcState)
            assert state.mode == "automatic"
            assert state.mode_value == 0

    def test_restores_on_exception(self):
        """Mode must be restored even when body raises."""
        app = MagicMock()
        modes = [0]
        type(app).Calculation = property(
            lambda self: modes[-1],
            lambda self, v: modes.append(v),
        )

        with pytest.raises(ValueError):
            with deferred_calc(app) as state:
                assert app.Calculation == 1
                raise ValueError("boom")

        # Must restore to automatic despite the exception
        assert app.Calculation == 0

    def test_set_fails_on_entry_still_yields(self):
        """If switching to MANUAL fails, should still yield (with auto-calc)."""
        app = MagicMock()
        call_count = [0]

        def get_calc():
            return 0  # always automatic

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
            return 0  # always reads as automatic

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
        project.Calculate.return_value = None
        type(project).Name = property(lambda self: (_ for _ in ()).throw(Exception("stale proxy")))
        result = calculate_project(app, project=project)
        assert result["recalculated"] is True
        assert result["error"] is None


# ---------------------------------------------------------------------------
# calculate_project
# ---------------------------------------------------------------------------

class TestCalculateProject:
    def test_calculate_all(self):
        app = MagicMock()
        result = calculate_project(app)
        app.CalculateAll.assert_called_once()
        assert result["recalculated"] is True
        assert result["scope"] == "all"
        assert result["error"] is None

    def test_calculate_single_project(self):
        app = MagicMock()
        project = MagicMock()
        project.Name = "test.mpp"
        result = calculate_project(app, project=project)
        project.Calculate.assert_called_once()
        app.CalculateAll.assert_not_called()
        assert result["recalculated"] is True
        assert result["scope"] == "project"

    def test_calculate_all_error(self):
        app = MagicMock()
        app.CalculateAll.side_effect = Exception("COM died")
        result = calculate_project(app)
        assert result["recalculated"] is False
        assert "COM died" in result["error"]

    def test_calculate_project_error(self):
        app = MagicMock()
        project = MagicMock()
        project.Calculate.side_effect = Exception("Recalc failed")
        result = calculate_project(app, project=project)
        assert result["recalculated"] is False
        assert result["scope"] == "project"
        assert "Recalc failed" in result["error"]


# ---------------------------------------------------------------------------
# get_calc_state
# ---------------------------------------------------------------------------

class TestGetCalcState:
    def test_returns_state_without_modifying(self):
        app = MagicMock()
        app.Calculation = 1  # manual
        state = get_calc_state(app)
        assert state.mode == "manual"
        assert state.mode_value == 1
        assert state.was_deferred is False
        assert state.original_mode is None
        # Verify Calculation was only read, not set
        assert app.Calculation == 1


# ---------------------------------------------------------------------------
# Integration: deferred_calc + calculate_project
# ---------------------------------------------------------------------------

class TestDeferredCalcIntegration:
    def test_batch_workflow(self):
        """Simulate the intended batch workflow."""
        app = MagicMock()
        modes = [0]  # start automatic
        type(app).Calculation = property(
            lambda self: modes[-1],
            lambda self, v: modes.append(v),
        )

        # 1. Defer calc
        with deferred_calc(app) as state:
            assert state.was_deferred is True
            # 2. Do "batch writes" (simulated)
            pass

        # 3. Mode is restored to automatic
        assert app.Calculation == 0

        # 4. Explicit recalc
        result = calculate_project(app)
        assert result["recalculated"] is True

    def test_nested_deferred_calc_is_noop(self):
        """Inner deferred_calc should be a no-op if already manual."""
        app = MagicMock()
        modes = [0]  # start automatic
        type(app).Calculation = property(
            lambda self: modes[-1],
            lambda self, v: modes.append(v),
        )

        with deferred_calc(app) as outer:
            assert outer.was_deferred is True
            assert app.Calculation == 1

            with deferred_calc(app) as inner:
                # Already manual, so no defer needed
                assert inner.was_deferred is False
                assert inner.mode == "manual"

            # Inner exit should NOT restore (was_deferred=False)
            assert app.Calculation == 1

        # Outer exit restores to automatic
        assert app.Calculation == 0
