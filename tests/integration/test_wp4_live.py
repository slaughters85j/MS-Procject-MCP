"""
WP-4 Live Integration Tests: Calculate Policy

Tests deferred calculation against real MS Project.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.calc_policy import (
    CalcMode,
    get_calc_mode,
    set_calc_mode,
    deferred_calc,
    calculate_project,
    get_calc_state,
)


class TestCalcPolicy:
    """Real COM calculation policy."""

    def test_read_default_calc_mode(self, temp_mpp):
        app, proj, path = temp_mpp
        mode = get_calc_mode(app)
        assert isinstance(mode, CalcMode)

    def test_set_manual_and_restore(self, temp_mpp):
        app, proj, path = temp_mpp
        original = get_calc_mode(app)

        previous = set_calc_mode(app, CalcMode.MANUAL)
        assert get_calc_mode(app) == CalcMode.MANUAL

        set_calc_mode(app, original)
        assert get_calc_mode(app) == original

    def test_deferred_calc_context_manager(self, temp_mpp):
        """deferred_calc suppresses auto-calc and restores it."""
        app, proj, path = temp_mpp
        original = get_calc_mode(app)

        with deferred_calc(app) as state:
            # Should be manual inside the block
            current = get_calc_mode(app)
            assert current == CalcMode.MANUAL
            assert state.was_deferred == (original == CalcMode.AUTOMATIC)

            # Write without triggering recalc
            for t in proj.Tasks:
                if t is not None and not t.Summary and not t.Milestone:
                    t.Duration = proj.MinutesPerDay * 10
                    break

        # Should be restored after the block
        restored = get_calc_mode(app)
        assert restored == original

    def test_calculate_project_explicit(self, temp_mpp):
        """Explicit recalculation after deferred writes."""
        app, proj, path = temp_mpp

        with deferred_calc(app):
            for t in proj.Tasks:
                if t is not None and not t.Summary and not t.Milestone:
                    t.PercentComplete = 50
                    break


        result = calculate_project(app, proj)
        assert result["recalculated"] is True
        assert result["scope"] == "project"
        assert result["error"] is None

    def test_calc_state_snapshot(self, temp_mpp):
        app, proj, path = temp_mpp
        state = get_calc_state(app)
        assert state.mode in ("automatic", "manual")
        assert state.was_deferred is False

    def test_deferred_calc_batch_performance(self, temp_mpp):
        """
        Batch writes inside deferred_calc should not trigger per-write
        recalcs. We can't easily time this, but we verify it doesn't
        error out.
        """
        app, proj, path = temp_mpp
        mpd = proj.MinutesPerDay

        with deferred_calc(app):
            for t in proj.Tasks:
                if t is not None and not t.Summary and not t.Milestone:
                    t.Duration = mpd * 2
                    t.Text1 = "Green"

        result = calculate_project(app, proj)
        assert result["recalculated"] is True
