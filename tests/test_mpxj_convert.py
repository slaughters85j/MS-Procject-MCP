"""
Unit tests for the mpxj value helpers and object-to-dict converters, using mocked Java objects.
"""

from unittest.mock import MagicMock

from src.mpxj_values import _format_duration, _format_java_date, _java_to_python
from src.mpxj_convert import (
    _assignment_to_dict,
    _calendar_to_dict,
    _project_properties_to_dict,
    _resource_to_dict,
    _task_to_dict,
)
from tests.mpxj_fakes import (
    _make_mock_task,
    _make_mock_resource,
    _make_mock_assignment,
    _make_mock_calendar,
    _make_java_list,
    _make_mock_project,
)


class TestJavaToPython:
    def test_none_returns_none(self):
        assert _java_to_python(None) is None

    def test_integer_with_intValue(self):
        mock = MagicMock()
        mock.intValue.return_value = 42
        assert _java_to_python(mock) == 42

    def test_plain_int(self):
        assert _java_to_python(5) == 5

    def test_fallback_to_float(self):
        mock = MagicMock()
        mock.intValue.side_effect = TypeError
        mock.__float__ = MagicMock(return_value=3.14)
        result = _java_to_python(mock)
        assert result == 3.14

    def test_fallback_to_string(self):
        mock = MagicMock()
        mock.intValue.side_effect = TypeError
        mock.__float__ = MagicMock(side_effect=TypeError)
        mock.__str__ = MagicMock(return_value="fallback")
        result = _java_to_python(mock)
        assert result == "fallback"


class TestFormatJavaDate:
    def test_none_returns_none(self):
        assert _format_java_date(None) is None

    def test_string_passes_through(self):
        assert _format_java_date("2026-01-15T08:00") == "2026-01-15T08:00"

    def test_exception_returns_none(self):
        mock = MagicMock()
        mock.__str__ = MagicMock(side_effect=RuntimeError)
        assert _format_java_date(mock) is None


class TestFormatDuration:
    def test_none_returns_none(self):
        assert _format_duration(None) is None

    def test_valid_duration(self):
        dur = MagicMock()
        dur.getDuration.return_value = 5.0
        dur.getUnits.return_value = "DAYS"
        result = _format_duration(dur)
        assert result == {"amount": 5.0, "units": "DAYS"}

    def test_exception_returns_none(self):
        dur = MagicMock()
        dur.getDuration.side_effect = RuntimeError
        assert _format_duration(dur) is None


class TestTaskToDict:
    def test_basic_fields(self):
        task = _make_mock_task(uid=42, task_id=3, name="Design Phase")
        result = _task_to_dict(task)
        assert result["unique_id"] == 42
        assert result["id"] == 3
        assert result["name"] == "Design Phase"

    def test_schedule_dates(self):
        task = _make_mock_task(
            getStart=MagicMock(return_value="2026-03-01"),
            getFinish=MagicMock(return_value="2026-03-15"),
        )
        # Override the mock to use our custom getters
        task.getStart.return_value = "2026-03-01"
        task.getFinish.return_value = "2026-03-15"
        result = _task_to_dict(task)
        assert result["start"] == "2026-03-01"
        assert result["finish"] == "2026-03-15"

    def test_percent_complete(self):
        task = _make_mock_task()
        result = _task_to_dict(task)
        assert result["percent_complete"] == 50

    def test_milestone_flag(self):
        task = _make_mock_task(getMilestone=MagicMock(return_value=True))
        task.getMilestone.return_value = True
        result = _task_to_dict(task)
        assert result["milestone"] is True

    def test_predecessors_extraction(self):
        pred_task = MagicMock()
        pred_task.getUniqueID.return_value = 5
        pred_task.getName.return_value = "Predecessor"

        relation = MagicMock()
        relation.getTargetTask.return_value = pred_task
        relation.getType.return_value = "FS"
        relation.getLag.return_value = None

        preds = _make_java_list([relation])

        task = _make_mock_task()
        task.getPredecessors.return_value = preds

        result = _task_to_dict(task)
        assert "predecessors" in result
        assert len(result["predecessors"]) == 1
        assert result["predecessors"][0]["task_unique_id"] == 5
        assert result["predecessors"][0]["task_name"] == "Predecessor"

    def test_resource_names_extraction(self):
        res = MagicMock()
        res.getName.return_value = "Alice"

        asn = MagicMock()
        asn.getResource.return_value = res

        assignments = _make_java_list([asn])
        task = _make_mock_task()
        task.getResourceAssignments.return_value = assignments

        result = _task_to_dict(task)
        assert result["resource_names"] == ["Alice"]

    def test_none_fields_excluded(self):
        task = _make_mock_task(getNotes=MagicMock(return_value=None))
        task.getNotes.return_value = None
        result = _task_to_dict(task)
        assert "notes" not in result

    def test_calendar_name(self):
        cal = MagicMock()
        cal.getName.return_value = "Night Shift"
        task = _make_mock_task()
        task.getCalendar.return_value = cal
        result = _task_to_dict(task)
        assert result["calendar_name"] == "Night Shift"


class TestResourceToDict:
    def test_basic_fields(self):
        res = _make_mock_resource(uid=7, res_id=3, name="Bob")
        result = _resource_to_dict(res)
        assert result["unique_id"] == 7
        assert result["id"] == 3
        assert result["name"] == "Bob"
        assert result["type"] == "WORK"
        assert result["initials"] == "R1"

    def test_email(self):
        res = _make_mock_resource()
        result = _resource_to_dict(res)
        assert result["email_address"] == "res@example.com"

    def test_max_units(self):
        res = _make_mock_resource()
        result = _resource_to_dict(res)
        assert result["max_units"] == 100


class TestAssignmentToDict:
    def test_basic_fields(self):
        asn = _make_mock_assignment(uid=99, task_uid=10, task_name="T1", res_uid=5, res_name="R1")
        result = _assignment_to_dict(asn)
        assert result["unique_id"] == 99
        assert result["task_unique_id"] == 10
        assert result["task_name"] == "T1"
        assert result["resource_unique_id"] == 5
        assert result["resource_name"] == "R1"

    def test_units_and_dates(self):
        asn = _make_mock_assignment()
        result = _assignment_to_dict(asn)
        assert result["units"] == 100
        assert result["start"] == "2026-01-15T08:00"
        assert result["finish"] == "2026-01-20T17:00"
        assert result["percent_work_complete"] == 50


class TestCalendarToDict:
    def test_basic_fields(self):
        cal = _make_mock_calendar(uid=1, name="Standard")
        result = _calendar_to_dict(cal)
        assert result["unique_id"] == 1
        assert result["name"] == "Standard"

    def test_parent_calendar(self):
        parent = MagicMock()
        parent.getName.return_value = "Base Calendar"

        cal = _make_mock_calendar()
        cal.getParent.return_value = parent

        result = _calendar_to_dict(cal)
        assert result["base_calendar"] == "Base Calendar"


class TestProjectPropertiesToDict:
    def test_basic_properties(self):
        project = _make_mock_project()
        props = project.getProjectProperties()
        result = _project_properties_to_dict(props)
        assert result["project_title"] == "Test Project"
        assert result["author"] == "John"
        assert result["manager"] == "Jane"
        assert result["company"] == "Acme"

    def test_schedule_settings(self):
        project = _make_mock_project()
        props = project.getProjectProperties()
        result = _project_properties_to_dict(props)
        assert result["minutes_per_day"] == 480
        assert result["minutes_per_week"] == 2400
        assert result["days_per_month"] == 20

    def test_currency(self):
        project = _make_mock_project()
        props = project.getProjectProperties()
        result = _project_properties_to_dict(props)
        assert result["currency_symbol"] == "$"
