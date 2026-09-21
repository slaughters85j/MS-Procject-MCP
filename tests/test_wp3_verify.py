"""
WP-3: Verify-After-Write Tests

Tests for drift detection, tolerance matching, and field verification.
Runs on any platform — no COM required.

NOTE: Testing against live MS Project remains required.
"""

import os
import sys
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.verify_write import (
    DriftReason,
    FieldResult,
    VerifyResult,
    verify_fields,
    verify_task_write,
    read_task_fields,
    _values_match,
    _classify_drift,
    DATE_TOLERANCE,
    DURATION_TOLERANCE_MINUTES,
    COST_TOLERANCE,
)


# ---------------------------------------------------------------------------
# Value matching
# ---------------------------------------------------------------------------

class TestValuesMatch:
    """Test type-aware tolerance matching."""

    def test_exact_match_string(self):
        assert _values_match("Name", "Task A", "Task A")

    def test_exact_match_int(self):
        assert _values_match("PercentComplete", 50, 50)

    def test_none_both(self):
        assert _values_match("Notes", None, None)

    def test_none_one_side(self):
        assert not _values_match("Name", "Hello", None)
        assert not _values_match("Name", None, "Hello")

    def test_string_case_insensitive(self):
        assert _values_match("Name", "Task A", "task a")

    def test_string_whitespace_trimmed(self):
        assert _values_match("Name", "  Task A  ", "Task A")

    def test_date_within_tolerance(self):
        base = datetime(2025, 6, 15, 8, 0)
        shifted = base + timedelta(hours=12)
        assert _values_match("Start", base, shifted)

    def test_date_outside_tolerance(self):
        base = datetime(2025, 6, 15, 8, 0)
        shifted = base + timedelta(days=3)
        assert not _values_match("Start", base, shifted)

    def test_duration_within_tolerance(self):
        # Durations are in minutes from COM
        assert _values_match("Duration", 480, 500)  # 20 min diff

    def test_duration_outside_tolerance(self):
        assert not _values_match("Duration", 480, 960)  # 8hrs diff

    def test_cost_within_tolerance(self):
        assert _values_match("Cost", 1500.00, 1500.005)

    def test_cost_outside_tolerance(self):
        assert not _values_match("Cost", 1500.00, 1502.00)

    def test_different_types_no_match(self):
        assert not _values_match("Field", 42, "42")


# ---------------------------------------------------------------------------
# Drift classification
# ---------------------------------------------------------------------------

class TestDriftClassification:
    """Test drift reason detection."""

    def test_date_drift_within_tolerance(self):
        base = datetime(2025, 6, 15, 8, 0)
        shifted = base + timedelta(hours=6)
        reason, detail = _classify_drift("Start", base, shifted)
        assert reason == DriftReason.RECALCULATION
        assert "tolerance" in detail.lower()

    def test_date_drift_exceeds_tolerance(self):
        base = datetime(2025, 6, 15, 8, 0)
        shifted = base + timedelta(days=5)
        reason, detail = _classify_drift("Start", base, shifted)
        assert reason == DriftReason.RECALCULATION
        assert "exceeds" in detail.lower()

    def test_duration_rounding(self):
        reason, detail = _classify_drift("Duration", 480, 500)
        assert reason == DriftReason.ROUNDING

    def test_duration_recalculation(self):
        reason, detail = _classify_drift("Duration", 480, 960)
        assert reason == DriftReason.RECALCULATION

    def test_cost_rounding(self):
        reason, detail = _classify_drift("Cost", 100.0, 100.005)
        assert reason == DriftReason.ROUNDING

    def test_string_normalization(self):
        reason, detail = _classify_drift("Name", "TASK A", "task a")
        assert reason == DriftReason.NORMALIZATION

    def test_constraint_field(self):
        reason, detail = _classify_drift("ConstraintType", 0, 2)
        assert reason == DriftReason.CONSTRAINT

    def test_unknown_drift(self):
        reason, detail = _classify_drift("PercentComplete", 50, 75)
        assert reason == DriftReason.UNKNOWN


# ---------------------------------------------------------------------------
# verify_fields integration
# ---------------------------------------------------------------------------

class TestVerifyFields:
    """Test the main verify_fields function."""

    def test_all_match(self):
        requested = {"Name": "Task A", "PercentComplete": 50}
        actual = {"Name": "Task A", "PercentComplete": 50}
        result = verify_fields(requested, actual)
        assert result.success
        assert result.field_count == 2
        assert result.matched_count == 2
        assert result.drifted_count == 0

    def test_one_drifted(self):
        requested = {"Name": "Task A", "PercentComplete": 50}
        actual = {"Name": "Task A", "PercentComplete": 75}
        result = verify_fields(requested, actual)
        assert not result.success
        assert result.drifted_count == 1
        assert result.drifted_fields[0].field_name == "PercentComplete"

    def test_all_drifted(self):
        requested = {"Name": "Original", "Duration": 480}
        actual = {"Name": "Changed", "Duration": 960}
        result = verify_fields(requested, actual)
        assert not result.success
        assert result.drifted_count == 2

    def test_missing_field_in_actual(self):
        requested = {"Name": "Task A", "Notes": "Hello"}
        actual = {"Name": "Task A"}
        result = verify_fields(requested, actual)
        assert result.drifted_count == 1

    def test_date_drift_within_tolerance_is_success(self):
        base = datetime(2025, 6, 15, 8, 0)
        requested = {"Start": base}
        actual = {"Start": base + timedelta(hours=6)}
        result = verify_fields(requested, actual)
        assert result.success  # Within tolerance
        assert result.matched_count == 1

    def test_to_dict_serializable(self):
        """Ensure output is JSON-serializable."""
        import json
        requested = {"Start": datetime(2025, 6, 15)}
        actual = {"Start": datetime(2025, 6, 16)}
        result = verify_fields(requested, actual)
        d = result.to_dict()
        json.dumps(d)  # Should not raise


# ---------------------------------------------------------------------------
# COM integration (mocked)
# ---------------------------------------------------------------------------

class TestReadTaskFields:
    """Test reading fields from a mock COM task."""

    def test_reads_existing_attrs(self):
        task = MagicMock()
        task.Name = "Task A"
        task.Duration = 480
        values, errors = read_task_fields(task, ["Name", "Duration"])
        assert values["Name"] == "Task A"
        assert values["Duration"] == 480
        assert len(errors) == 0

    def test_missing_attr_returns_none_with_error(self):
        task = MagicMock(spec=[])  # Empty spec = no attributes
        values, errors = read_task_fields(task, ["NonExistent"])
        assert values["NonExistent"] is None
        assert "NonExistent" in errors

    def test_exception_returns_none_with_error(self):
        task = MagicMock()
        type(task).Name = property(lambda self: (_ for _ in ()).throw(
            Exception("COM error")
        ))
        values, errors = read_task_fields(task, ["Name"])
        assert values["Name"] is None
        assert "Name" in errors
        assert "COM error" in errors["Name"]


class TestVerifyTaskWrite:
    """Test the COM-integrated verify path."""

    def test_verify_success(self):
        task = MagicMock()
        task.Name = "Task A"
        task.PercentComplete = 50
        result = verify_task_write(
            task, {"Name": "Task A", "PercentComplete": 50}, max_retries=1
        )
        assert result.success

    def test_verify_drift_detected(self):
        task = MagicMock()
        task.Name = "Task A"
        task.PercentComplete = 75  # Drifted from 50
        result = verify_task_write(
            task, {"Name": "Task A", "PercentComplete": 50}, max_retries=1
        )
        assert not result.success
        assert result.drifted_count == 1

    def test_verify_result_is_serializable(self):
        import json
        task = MagicMock()
        task.Name = "Task A"
        result = verify_task_write(task, {"Name": "Task A"}, max_retries=1)
        json.dumps(result.to_dict())

    def test_verify_error_field_populated(self):
        """Read errors should be surfaced in FieldResult.error."""
        task = MagicMock(spec=[])  # No attributes
        result = verify_task_write(task, {"BadField": "value"}, max_retries=1)
        assert not result.success
        error_field = result.fields[0]
        assert error_field.error is not None

    def test_retry_succeeds_on_later_attempt(self):
        """If COM recalc settles, retry should succeed."""
        task = MagicMock()
        call_count = {"n": 0}
        original_getattr = task.__class__.__getattr__

        def delayed_value(self, name):
            if name == "PercentComplete":
                call_count["n"] += 1
                if call_count["n"] <= 1:
                    return 0  # First read: stale
                return 50  # Later reads: correct
            return original_getattr(self, name)

        type(task).__getattr__ = delayed_value
        task.Name = "Task A"

        result = verify_task_write(
            task,
            {"Name": "Task A", "PercentComplete": 50},
            max_retries=3,
            retry_delays=(0.01, 0.01, 0.01),  # Fast for tests
        )
        assert result.success


class TestFieldResult:
    """Test FieldResult data class."""

    def test_to_dict_with_datetime(self):
        fr = FieldResult(
            field_name="Start",
            requested=datetime(2025, 6, 15),
            actual=datetime(2025, 6, 16),
            matched=False,
            drifted=True,
            drift_reason=DriftReason.RECALCULATION.value,
        )
        d = fr.to_dict()
        assert isinstance(d["requested"], str)
        assert "2025-06-15" in d["requested"]
