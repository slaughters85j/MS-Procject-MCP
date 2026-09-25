"""
Calculate Policy

Tests for calc_policy.py: CalcMode, CalcState, get/set_calc_mode,
calculate_project and get_calc_state.
All tests mock COM — no live MS Project required.
"""

import pytest
from unittest.mock import MagicMock, PropertyMock
from src.calc_policy import (
    CalcMode,
    CalcState,
    get_calc_mode,
    set_calc_mode,
    calculate_project,
    get_calc_state,
)


# ---------------------------------------------------------------------------
# CalcMode enum
# ---------------------------------------------------------------------------

class TestCalcMode:
    def test_automatic_value(self):
        assert CalcMode.AUTOMATIC == -1

    def test_manual_value(self):
        assert CalcMode.MANUAL == 0

    def test_from_int(self):
        assert CalcMode(-1) == CalcMode.AUTOMATIC
        assert CalcMode(0) == CalcMode.MANUAL

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            CalcMode(99)

    def test_int_cast(self):
        assert int(CalcMode.AUTOMATIC) == -1
        assert int(CalcMode.MANUAL) == 0


# ---------------------------------------------------------------------------
# CalcState dataclass
# ---------------------------------------------------------------------------

class TestCalcState:
    def test_to_dict(self):
        state = CalcState(
            mode="automatic",
            mode_value=-1,
            was_deferred=True,
            original_mode=-1,
        )
        d = state.to_dict()
        assert d["mode"] == "automatic"
        assert d["mode_value"] == -1
        assert d["was_deferred"] is True
        assert d["original_mode"] == -1

    def test_defaults(self):
        state = CalcState(mode="manual", mode_value=0, was_deferred=False)
        assert state.original_mode is None


# ---------------------------------------------------------------------------
# get_calc_mode
# ---------------------------------------------------------------------------

class TestGetCalcMode:
    def test_reads_automatic(self):
        app = MagicMock()
        app.Calculation = -1
        assert get_calc_mode(app) == CalcMode.AUTOMATIC

    def test_reads_manual(self):
        app = MagicMock()
        app.Calculation = 0
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
        app.Calculation = -1  # currently automatic
        previous = set_calc_mode(app, CalcMode.MANUAL)
        assert previous == CalcMode.AUTOMATIC
        assert app.Calculation == 0

    def test_set_same_mode(self):
        app = MagicMock()
        app.Calculation = 0
        previous = set_calc_mode(app, CalcMode.MANUAL)
        assert previous == CalcMode.MANUAL

    def test_com_error_raises_runtime(self):
        app = MagicMock()
        app.Calculation = -1
        # Make the setter raise
        type(app).Calculation = PropertyMock(
            return_value=0,
            side_effect=[0, Exception("COM error")]
        )
        with pytest.raises(RuntimeError, match="Could not set"):
            set_calc_mode(app, CalcMode.MANUAL)


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
        project.FullName = r"C:\b\test.mpp"
        other = MagicMock()
        other.FullName = r"C:\a\other.mpp"
        app.ActiveProject = other

        def window_activate(WindowName):
            app.ActiveProject = project
        app.WindowActivate.side_effect = window_activate
        result = calculate_project(app, project=project)
        # Project.Activate() fails in hidden instances; activation goes through the window.
        app.WindowActivate.assert_called_once_with(WindowName="test.mpp")
        project.Activate.assert_not_called()
        app.CalculateProject.assert_called_once()
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
        app.ActiveProject = project
        app.CalculateProject.side_effect = Exception("Recalc failed")
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
        app.Calculation = 0  # manual
        state = get_calc_state(app)
        assert state.mode == "manual"
        assert state.mode_value == 0
        assert state.was_deferred is False
        assert state.original_mode is None
        # Verify Calculation was only read, not set
        assert app.Calculation == 0
