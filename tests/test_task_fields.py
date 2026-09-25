"""
Tests for src.task_fields (update_task / bulk_update_tasks validation) and src.bulk_fields.
"""

import datetime
from unittest.mock import MagicMock

import pytest

from src.task_fields import validate_changes, apply_changes
from src.bulk_fields import normalize_fields, normalized_or_error


def _proj():
    proj = MagicMock()
    proj.DefaultStartTime = datetime.datetime(1899, 12, 30, 8, 0)
    proj.DefaultFinishTime = datetime.datetime(1899, 12, 30, 17, 0)
    proj.HoursPerDay = 8.0
    return proj


class TestValidateChanges:
    def test_none_means_unchanged(self):
        assert validate_changes(_proj(), {"name": None, "notes": None}) == {}

    def test_empty_string_clears_text_fields(self):
        assert validate_changes(_proj(), {"notes": "", "rag": "", "text2": ""}) == {"notes": "", "rag": "", "text2": ""}

    @pytest.mark.parametrize("changes", [
        {"percent_complete": 150}, {"priority": 5000}, {"duration_days": -1}, {"rag": "purple"},
        {"task_type": "bogus"}, {"name": "  "}, {"bogus_key": 1}, {"start": "06/10/2031"},
        {"start": "2031-06-10", "finish": "2031-06-01"},
    ])
    def test_invalid_input_is_rejected(self, changes):
        with pytest.raises(ValueError):
            validate_changes(_proj(), changes)

    def test_task_type_maps_to_pjtaskfixedtype(self):
        assert validate_changes(_proj(), {"task_type": "FixedWork"}) == {"task_type": 2}

    def test_finish_is_end_of_day(self):
        values = validate_changes(_proj(), {"finish": "2031-06-05"})
        assert values["finish"].hour == 17


class TestApplyChanges:
    def test_duration_uses_hours_per_day(self):
        proj, task = _proj(), MagicMock()
        proj.HoursPerDay = 10.0
        changed, _ = apply_changes(proj, task, {"duration_days": 2.0})
        assert task.Duration == 1200 and changed == ["duration_days"]

    def test_mode_is_written_before_dates(self):
        order = []
        task = MagicMock()
        type(task).Manual = property(lambda s: None, lambda s, v: order.append("manual"))
        type(task).Start = property(lambda s: "2031-06-01 08:00:00", lambda s, v: order.append("start"))
        apply_changes(_proj(), task, validate_changes(_proj(), {"start": "2031-06-01", "manual": True}))
        assert order == ["manual", "start"]


class TestBulkFields:
    def test_date_strings_are_converted(self):
        out = normalize_fields(_proj(), MagicMock(), {"Start": "2031-05-04", "Finish": "2031-05-08", "Name": "x"})
        assert out["Start"] == datetime.datetime(2031, 5, 4, 8, 0, tzinfo=datetime.timezone.utc)
        assert out["Finish"].hour == 17 and out["Name"] == "x"

    def test_unknown_field_is_an_error(self):
        task = MagicMock(spec=["Name"])
        fields, error = normalized_or_error(_proj(), task, {"NotAField": 1})
        assert fields is None and "NotAField" in error

    def test_bad_date_is_an_error(self):
        fields, error = normalized_or_error(_proj(), MagicMock(), {"Start": "05/04/2031"})
        assert fields is None and "Start" in error
