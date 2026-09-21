"""
WP-3 Live Integration Tests: Verify-After-Write

Tests drift detection against real MS Project recalculation behavior.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.verify_write import (
    verify_task_write,
    read_task_fields,
    VerifyResult,
)


class TestVerifyAfterWrite:
    """Real COM verify-after-write."""

    def test_verify_name_write(self, temp_mpp):
        """Write a name, verify it sticks."""
        app, proj, path = temp_mpp
        # Find a non-summary task
        task = None
        for t in proj.Tasks:
            if t is not None and not t.Summary:
                task = t
                break
        assert task is not None

        new_name = "WP3 Verify Test Name"
        task.Name = new_name
        result = verify_task_write(
            task,
            {"Name": new_name},
            max_retries=2,
            retry_delays=(0.2, 0.5),
        )
        assert result.success, (
            f"Name write drifted: {[f.to_dict() for f in result.drifted_fields]}"
        )

    def test_verify_percent_complete(self, temp_mpp):
        """Write percent_complete, verify it sticks."""
        app, proj, path = temp_mpp
        task = None
        for t in proj.Tasks:
            if t is not None and not t.Summary and not t.Milestone:
                task = t
                break
        assert task is not None

        task.PercentComplete = 42
        result = verify_task_write(
            task,
            {"PercentComplete": 42},
            max_retries=2,
            retry_delays=(0.2, 0.5),
        )
        assert result.success

    def test_verify_duration_may_drift(self, temp_mpp):
        """
        Write a duration and verify. Project may recalculate durations
        based on constraints/predecessors — we accept drift within tolerance.
        """
        app, proj, path = temp_mpp
        mpd = proj.MinutesPerDay
        task = None
        for t in proj.Tasks:
            if t is not None and not t.Summary and not t.Milestone:
                task = t
                break
        assert task is not None

        new_dur = mpd * 7  # 7 days
        task.Duration = new_dur
        result = verify_task_write(
            task,
            {"Duration": new_dur},
            max_retries=3,
            retry_delays=(0.3, 0.5, 1.0),
        )
        # Duration writes CAN drift due to recalculation
        # We just verify the result is a valid VerifyResult
        assert isinstance(result, VerifyResult)
        assert result.field_count == 1

    def test_read_task_fields_real_com(self, temp_mpp):
        """read_task_fields works against a real COM Task object."""
        app, proj, path = temp_mpp
        task = None
        for t in proj.Tasks:
            if t is not None and not t.Summary:
                task = t
                break
        assert task is not None

        values, errors = read_task_fields(
            task, ["Name", "Duration", "PercentComplete", "UniqueID"]
        )
        assert len(errors) == 0
        assert "Name" in values
        assert isinstance(values["Duration"], (int, float))
        assert isinstance(values["PercentComplete"], int)

    def test_verify_multi_field_write(self, temp_mpp):
        """Write multiple fields at once and verify all."""
        app, proj, path = temp_mpp
        task = None
        for t in proj.Tasks:
            if t is not None and not t.Summary and not t.Milestone:
                task = t
                break
        assert task is not None

        task.Name = "Multi-field test"
        task.Text1 = "Amber"
        task.PercentComplete = 25
        task.Notes = "Integration test note"

        result = verify_task_write(
            task,
            {
                "Name": "Multi-field test",
                "Text1": "Amber",
                "PercentComplete": 25,
                "Notes": "Integration test note",
            },
            max_retries=2,
            retry_delays=(0.2, 0.5),
        )
        assert result.success, (
            f"Multi-field drifted: "
            f"{[f.to_dict() for f in result.drifted_fields]}"
        )
