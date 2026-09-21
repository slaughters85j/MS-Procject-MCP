"""
Tests for Sprint 4: mpxj fast-read path (src/mpxj_reader.py, src/mpxj_tools.py).

All tests use mocked mpxj/jpype — no JVM or Java required.
Covers:
  - mpxj_reader: file validation, task/resource/assignment/calendar/project extraction,
    error handling, JVM lifecycle, source metadata
  - mpxj_tools: tool registration, safe_path enforcement, response management
    (pagination, strip_empty, format_response), error responses
  - annotations and tool_guide integration
"""

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.mpxj_reader import (
    _validate_file,
    _task_to_dict,
    _resource_to_dict,
    _assignment_to_dict,
    _calendar_to_dict,
    _project_properties_to_dict,
    _source_metadata,
    _java_to_python,
    _format_java_date,
    _format_duration,
    read_tasks,
    read_resources,
    read_assignments,
    read_calendars,
    read_project_info,
    is_mpxj_available,
    MpxjError,
    MpxjNotAvailableError,
    MpxjFileError,
    MpxjParseError,
    _VALID_EXTENSIONS,
)

from src.response import (
    paginate, strip_empty, strip_empty_list, format_response,
    DEFAULT_PAGE_LIMIT,
)


# ===========================================================================
# Fixtures and helpers
# ===========================================================================

@pytest.fixture
def tmp_mpp(tmp_path):
    """Create a temporary .mpp file for testing."""
    f = tmp_path / "test_project.mpp"
    f.write_bytes(b"fake mpp content")
    return str(f)


@pytest.fixture
def tmp_mpp_readonly(tmp_path):
    """Create a read-only .mpp file."""
    f = tmp_path / "readonly.mpp"
    f.write_bytes(b"fake mpp content")
    os.chmod(str(f), 0o000)
    yield str(f)
    os.chmod(str(f), 0o644)


def _make_mock_task(uid=1, task_id=1, name="Task 1", **overrides):
    """Create a mock Java task object."""
    task = MagicMock()
    task.getUniqueID.return_value = uid
    task.getID.return_value = task_id
    task.getName.return_value = name
    task.getOutlineLevel.return_value = 1
    task.getOutlineNumber.return_value = "1"
    task.getWBS.return_value = "1"
    task.getSummary.return_value = False
    task.getStart.return_value = "2026-01-15T08:00"
    task.getFinish.return_value = "2026-01-20T17:00"
    task.getDuration.return_value = None
    task.getActualStart.return_value = None
    task.getActualFinish.return_value = None
    task.getBaselineStart.return_value = None
    task.getBaselineFinish.return_value = None
    task.getBaselineDuration.return_value = None
    task.getPercentageComplete.return_value = 50
    task.getPhysicalPercentComplete.return_value = None
    task.getConstraintType.return_value = None
    task.getConstraintDate.return_value = None
    task.getDeadline.return_value = None
    task.getPriority.return_value = None
    task.getType.return_value = None
    task.getMilestone.return_value = False
    task.getCritical.return_value = False
    task.getActive.return_value = True
    task.getTotalSlack.return_value = None
    task.getFreeSlack.return_value = None
    task.getCost.return_value = None
    task.getActualCost.return_value = None
    task.getBaselineCost.return_value = None
    task.getWork.return_value = None
    task.getActualWork.return_value = None
    task.getRemainingWork.return_value = None
    task.getNotes.return_value = None
    task.getCalendar.return_value = None
    task.getPredecessors.return_value = None
    task.getResourceAssignments.return_value = None

    for k, v in overrides.items():
        getattr(task, k).return_value = v
    return task


def _make_mock_resource(uid=1, res_id=1, name="Resource 1"):
    """Create a mock Java resource object."""
    res = MagicMock()
    res.getUniqueID.return_value = uid
    res.getID.return_value = res_id
    res.getName.return_value = name
    res.getType.return_value = "WORK"
    res.getInitials.return_value = "R1"
    res.getGroup.return_value = None
    res.getEmailAddress.return_value = "res@example.com"
    res.getMaxUnits.return_value = 100
    res.getStandardRate.return_value = None
    res.getOvertimeRate.return_value = None
    res.getCostPerUse.return_value = None
    res.getCost.return_value = None
    res.getActualCost.return_value = None
    res.getWork.return_value = None
    res.getActualWork.return_value = None
    res.getRemainingWork.return_value = None
    res.getAvailableFrom.return_value = None
    res.getAvailableTo.return_value = None
    res.getNotes.return_value = None
    res.getCalendar.return_value = None
    return res


def _make_mock_assignment(uid=1, task_uid=10, task_name="T1", res_uid=5, res_name="R1"):
    """Create a mock Java resource assignment."""
    asn = MagicMock()
    asn.getUniqueID.return_value = uid

    task = MagicMock()
    task.getUniqueID.return_value = task_uid
    task.getName.return_value = task_name
    asn.getTask.return_value = task

    res = MagicMock()
    res.getUniqueID.return_value = res_uid
    res.getName.return_value = res_name
    asn.getResource.return_value = res

    asn.getUnits.return_value = 100
    asn.getWork.return_value = None
    asn.getActualWork.return_value = None
    asn.getRemainingWork.return_value = None
    asn.getCost.return_value = None
    asn.getActualCost.return_value = None
    asn.getStart.return_value = "2026-01-15T08:00"
    asn.getFinish.return_value = "2026-01-20T17:00"
    asn.getPercentageWorkComplete.return_value = 50
    return asn


def _make_mock_calendar(uid=1, name="Standard"):
    """Create a mock Java calendar."""
    cal = MagicMock()
    cal.getUniqueID.return_value = uid
    cal.getName.return_value = name
    cal.getParent.return_value = None
    cal.getCalendarExceptions.return_value = MagicMock(size=MagicMock(return_value=0))
    return cal


def _make_java_list(items):
    """Create a mock Java List with .size() and .get(i)."""
    jlist = MagicMock()
    jlist.size.return_value = len(items)
    jlist.get.side_effect = lambda i: items[i]
    return jlist


def _make_mock_project(tasks=None, resources=None, assignments=None, calendars=None):
    """Create a mock mpxj ProjectFile."""
    project = MagicMock()

    if tasks is None:
        tasks = [_make_mock_task(uid=0, task_id=0, name="Project Summary")]
    project.getTasks.return_value = _make_java_list(tasks)

    if resources is None:
        resources = []
    project.getResources.return_value = _make_java_list(resources)

    if assignments is None:
        assignments = []
    project.getResourceAssignments.return_value = _make_java_list(assignments)

    if calendars is None:
        calendars = []
    project.getCalendars.return_value = _make_java_list(calendars)

    props = MagicMock()
    props.getProjectTitle.return_value = "Test Project"
    props.getSubject.return_value = None
    props.getAuthor.return_value = "John"
    props.getManager.return_value = "Jane"
    props.getCompany.return_value = "Acme"
    props.getCategory.return_value = None
    props.getComments.return_value = None
    props.getStartDate.return_value = "2026-01-01"
    props.getFinishDate.return_value = "2026-12-31"
    props.getCurrentDate.return_value = None
    props.getStatusDate.return_value = None
    props.getCreationDate.return_value = None
    props.getLastSaved.return_value = None
    props.getScheduleFrom.return_value = None
    props.getMinutesPerDay.return_value = 480
    props.getMinutesPerWeek.return_value = 2400
    props.getDaysPerMonth.return_value = 20
    props.getDefaultCalendarName.return_value = "Standard"
    props.getCurrencySymbol.return_value = "$"
    project.getProjectProperties.return_value = props

    return project


# ===========================================================================
# Test: File validation
# ===========================================================================

class TestValidateFile:
    def test_valid_mpp_file(self, tmp_mpp):
        result = _validate_file(tmp_mpp)
        assert os.path.isabs(result)
        assert result.endswith(".mpp")

    def test_empty_path_raises(self):
        with pytest.raises(MpxjFileError, match="file_path is required"):
            _validate_file("")

    def test_whitespace_path_raises(self):
        with pytest.raises(MpxjFileError, match="file_path is required"):
            _validate_file("   ")

    def test_nonexistent_file_raises(self):
        with pytest.raises(MpxjFileError, match="File not found"):
            _validate_file("/nonexistent/path/project.mpp")

    def test_directory_raises(self, tmp_path):
        with pytest.raises(MpxjFileError, match="Not a file"):
            _validate_file(str(tmp_path))

    @pytest.mark.skipif(
        sys.platform == "win32", reason="chmod has no effect on Windows"
    )
    def test_unreadable_file_raises(self, tmp_mpp_readonly):
        with pytest.raises(MpxjFileError, match="not readable"):
            _validate_file(tmp_mpp_readonly)

    def test_wrong_extension_raises(self, tmp_path):
        f = tmp_path / "project.xlsx"
        f.write_bytes(b"data")
        with pytest.raises(MpxjFileError, match="Unsupported file extension"):
            _validate_file(str(f))

    def test_all_valid_extensions(self, tmp_path):
        for ext in _VALID_EXTENSIONS:
            f = tmp_path / f"test{ext}"
            f.write_bytes(b"data")
            result = _validate_file(str(f))
            assert result.endswith(ext)


# ===========================================================================
# Test: Java-to-Python conversion helpers
# ===========================================================================

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


# ===========================================================================
# Test: Task extraction
# ===========================================================================

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


# ===========================================================================
# Test: Resource extraction
# ===========================================================================

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


# ===========================================================================
# Test: Assignment extraction
# ===========================================================================

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


# ===========================================================================
# Test: Calendar extraction
# ===========================================================================

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


# ===========================================================================
# Test: Project properties extraction
# ===========================================================================

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


# ===========================================================================
# Test: Source metadata
# ===========================================================================

class TestSourceMetadata:
    def test_structure(self):
        meta = _source_metadata("/path/to/file.mpp", "tasks", 42)
        assert meta["backend"] == "mpxj"
        assert meta["file_path"] == "/path/to/file.mpp"
        assert meta["entity_type"] == "tasks"
        assert meta["count"] == 42
        assert "read_at" in meta
        assert "+00:00" in meta["read_at"] or meta["read_at"].endswith("Z")
        assert "SAVED" in meta["note"]

    def test_note_mentions_saved(self):
        meta = _source_metadata("/f.mpp", "resources", 0)
        assert "SAVED" in meta["note"]
        assert "NOT reflected" in meta["note"]


# ===========================================================================
# Test: is_mpxj_available
# ===========================================================================

class TestIsMpxjAvailable:
    def test_returns_false_when_not_installed(self):
        with patch.dict(sys.modules, {"mpxj": None, "jpype": None}):
            # Force import error
            import importlib
            with patch("builtins.__import__", side_effect=ImportError):
                assert is_mpxj_available() is False

    def test_returns_true_when_installed(self):
        mock_mpxj = MagicMock()
        mock_jpype = MagicMock()
        with patch.dict(sys.modules, {"mpxj": mock_mpxj, "jpype": mock_jpype}):
            assert is_mpxj_available() is True


# ===========================================================================
# Test: read_tasks (end-to-end with mock)
# ===========================================================================

class TestReadTasks:
    @patch("src.mpxj_reader._open_project")
    def test_reads_tasks_skips_summary(self, mock_open, tmp_mpp):
        summary = _make_mock_task(uid=0, task_id=0, name="Project Summary")
        task1 = _make_mock_task(uid=1, task_id=1, name="Task 1")
        task2 = _make_mock_task(uid=2, task_id=2, name="Task 2")

        mock_open.return_value = _make_mock_project(
            tasks=[summary, task1, task2]
        )

        tasks, source = read_tasks(tmp_mpp)
        assert len(tasks) == 2
        assert tasks[0]["name"] == "Task 1"
        assert tasks[1]["name"] == "Task 2"
        assert source["backend"] == "mpxj"
        assert source["count"] == 2

    @patch("src.mpxj_reader._open_project")
    def test_empty_project(self, mock_open, tmp_mpp):
        summary = _make_mock_task(uid=0, task_id=0, name="Summary")
        mock_open.return_value = _make_mock_project(tasks=[summary])

        tasks, source = read_tasks(tmp_mpp)
        assert len(tasks) == 0
        assert source["count"] == 0

    def test_file_not_found(self):
        with pytest.raises(MpxjFileError, match="File not found"):
            read_tasks("/nonexistent/project.mpp")


# ===========================================================================
# Test: read_resources (end-to-end with mock)
# ===========================================================================

class TestReadResources:
    @patch("src.mpxj_reader._open_project")
    def test_reads_resources_skips_dummy(self, mock_open, tmp_mpp):
        dummy = _make_mock_resource(uid=0, res_id=0, name="")
        res1 = _make_mock_resource(uid=1, res_id=1, name="Alice")
        res2 = _make_mock_resource(uid=2, res_id=2, name="Bob")

        mock_open.return_value = _make_mock_project(
            resources=[dummy, res1, res2]
        )

        resources, source = read_resources(tmp_mpp)
        assert len(resources) == 2
        assert resources[0]["name"] == "Alice"
        assert source["entity_type"] == "resources"


# ===========================================================================
# Test: read_assignments (end-to-end with mock)
# ===========================================================================

class TestReadAssignments:
    @patch("src.mpxj_reader._open_project")
    def test_reads_assignments(self, mock_open, tmp_mpp):
        asn = _make_mock_assignment()
        mock_open.return_value = _make_mock_project(assignments=[asn])

        assignments, source = read_assignments(tmp_mpp)
        assert len(assignments) == 1
        assert source["entity_type"] == "assignments"


# ===========================================================================
# Test: read_calendars (end-to-end with mock)
# ===========================================================================

class TestReadCalendars:
    @patch("src.mpxj_reader._open_project")
    def test_reads_calendars(self, mock_open, tmp_mpp):
        cal = _make_mock_calendar(uid=1, name="Standard")
        mock_open.return_value = _make_mock_project(calendars=[cal])

        calendars, source = read_calendars(tmp_mpp)
        assert len(calendars) == 1
        assert calendars[0]["name"] == "Standard"
        assert source["entity_type"] == "calendars"


# ===========================================================================
# Test: read_project_info (end-to-end with mock)
# ===========================================================================

class TestReadProjectInfo:
    @patch("src.mpxj_reader._open_project")
    def test_reads_project_info(self, mock_open, tmp_mpp):
        mock_open.return_value = _make_mock_project()

        info, source = read_project_info(tmp_mpp)
        assert info["project_title"] == "Test Project"
        assert info["author"] == "John"
        assert source["entity_type"] == "project_info"


# ===========================================================================
# Test: safe_path enforcement in tools
# ===========================================================================

class TestSafePathEnforcement:
    def test_safe_path_rejects_outside_root(self, tmp_mpp, monkeypatch):
        """Verify safe_path raises ValueError for paths outside MSPROJECT_SAFE_ROOT."""
        from src import safe_path

        # Set safe root to a directory that doesn't contain tmp_mpp
        monkeypatch.setenv("MSPROJECT_SAFE_ROOT", "/some/other/directory")
        safe_path.reload_safe_root()

        try:
            with pytest.raises(ValueError, match="Path confinement violation"):
                safe_path.validate_safe_path(tmp_mpp)
        finally:
            # Reset
            monkeypatch.delenv("MSPROJECT_SAFE_ROOT", raising=False)
            safe_path.reload_safe_root()

    def test_safe_path_accepts_within_root(self, tmp_mpp, monkeypatch):
        """Verify safe_path accepts paths within MSPROJECT_SAFE_ROOT."""
        from src import safe_path

        parent_dir = os.path.dirname(tmp_mpp)
        monkeypatch.setenv("MSPROJECT_SAFE_ROOT", parent_dir)
        safe_path.reload_safe_root()

        try:
            result = safe_path.validate_safe_path(tmp_mpp)
            assert os.path.isabs(result)
        finally:
            monkeypatch.delenv("MSPROJECT_SAFE_ROOT", raising=False)
            safe_path.reload_safe_root()


# ===========================================================================
# Test: Response management integration
# ===========================================================================

class TestResponseManagement:
    def test_paginate_tasks(self):
        tasks = [{"unique_id": i, "name": f"Task {i}"} for i in range(50)]
        page, meta = paginate(tasks, offset=0, limit=10)
        assert len(page) == 10
        assert meta["total"] == 50
        assert meta["truncated"] is True
        assert meta["next_offset"] == 10

    def test_strip_empty_removes_none(self):
        task = {"unique_id": 1, "name": "T1", "notes": None, "cost": 0}
        result = strip_empty(task)
        assert "notes" not in result
        assert "cost" not in result  # zero is dropped for non-meaningful fields
        assert result["unique_id"] == 1

    def test_strip_empty_keeps_identity(self):
        task = {"unique_id": 0, "name": "", "id": 0}
        result = strip_empty(task)
        assert "unique_id" in result
        assert "name" in result
        assert "id" in result

    def test_format_response_compact_large(self):
        large = {"data": ["x" * 100] * 100}
        result = format_response(large)
        assert "\n" not in result  # compact format

    def test_format_response_indented_small(self):
        small = {"count": 1}
        result = format_response(small)
        assert "\n" in result  # indented format


# ===========================================================================
# Test: Tool registration
# ===========================================================================

class TestToolRegistration:
    def test_register_mpxj_tools(self):
        """Verify that register_mpxj_tools adds 5 tools to a mock FastMCP."""
        mock_mcp = MagicMock()
        registered_tools = {}

        def mock_tool_decorator():
            def decorator(func):
                registered_tools[func.__name__] = func
                return func
            return decorator

        mock_mcp.tool = mock_tool_decorator

        from src.mpxj_tools import register_mpxj_tools
        register_mpxj_tools(mock_mcp)

        expected = {
            "mpxj_read_tasks",
            "mpxj_read_resources",
            "mpxj_read_project_info",
            "mpxj_read_assignments",
            "mpxj_read_calendars",
        }
        assert set(registered_tools.keys()) == expected

    def test_tool_descriptions_mention_saved(self):
        """Verify each tool's docstring mentions SAVED file."""
        mock_mcp = MagicMock()
        registered_tools = {}

        def mock_tool_decorator():
            def decorator(func):
                registered_tools[func.__name__] = func
                return func
            return decorator

        mock_mcp.tool = mock_tool_decorator

        from src.mpxj_tools import register_mpxj_tools
        register_mpxj_tools(mock_mcp)

        for name, func in registered_tools.items():
            assert "SAVED" in func.__doc__, f"{name} docstring must mention SAVED"


# ===========================================================================
# Test: Error responses from tools
# ===========================================================================

class TestToolErrorResponses:
    def test_mpxj_file_error_response(self):
        """Verify MpxjFileError produces a proper JSON error response."""
        from src.mpxj_reader import MpxjFileError
        error = MpxjFileError("File not found: test.mpp")
        response = format_response({
            "error": True,
            "error_type": "MpxjFileError",
            "message": str(error),
        })
        parsed = json.loads(response)
        assert parsed["error"] is True
        assert parsed["error_type"] == "MpxjFileError"
        assert "File not found" in parsed["message"]

    def test_mpxj_parse_error_response(self):
        error = MpxjParseError("Failed to parse: corrupt file")
        response = format_response({
            "error": True,
            "error_type": "MpxjParseError",
            "message": str(error),
        })
        parsed = json.loads(response)
        assert parsed["error"] is True
        assert "corrupt" in parsed["message"]

    def test_value_error_from_safe_path(self):
        error = ValueError("Path confinement violation")
        response = format_response({
            "error": True,
            "error_type": "ValueError",
            "message": str(error),
        })
        parsed = json.loads(response)
        assert "confinement" in parsed["message"]


# ===========================================================================
# Test: Annotations integration
# ===========================================================================

class TestAnnotationsIntegration:
    def test_mpxj_tools_in_annotations(self):
        from src.annotations import TOOL_ANNOTATIONS

        mpxj_tools = [
            "mpxj_read_tasks",
            "mpxj_read_resources",
            "mpxj_read_project_info",
            "mpxj_read_assignments",
            "mpxj_read_calendars",
        ]

        for tool_name in mpxj_tools:
            assert tool_name in TOOL_ANNOTATIONS, f"{tool_name} missing from TOOL_ANNOTATIONS"
            ann = TOOL_ANNOTATIONS[tool_name]
            assert ann["readOnlyHint"] is True, f"{tool_name} must be readOnlyHint=True"
            assert ann["destructiveHint"] is False, f"{tool_name} must be destructiveHint=False"
            assert ann["idempotentHint"] is True, f"{tool_name} must be idempotentHint=True"


# ===========================================================================
# Test: Tool guide integration
# ===========================================================================

class TestToolGuideIntegration:
    def test_mpxj_category_in_tool_guide(self):
        from src.tool_guide import _TOOL_GUIDE

        assert "mpxj_fast_read" in _TOOL_GUIDE["tool_categories"]
        mpxj_tools = _TOOL_GUIDE["tool_categories"]["mpxj_fast_read"]
        assert "mpxj_read_tasks" in mpxj_tools
        assert "mpxj_read_resources" in mpxj_tools
        assert "mpxj_read_project_info" in mpxj_tools
        assert "mpxj_read_assignments" in mpxj_tools
        assert "mpxj_read_calendars" in mpxj_tools

    def test_server_instructions_mention_mpxj(self):
        from src.tool_guide import SERVER_INSTRUCTIONS

        assert "mpxj" in SERVER_INSTRUCTIONS.lower()
        assert "SAVED" in SERVER_INSTRUCTIONS


# ===========================================================================
# Test: Exception hierarchy
# ===========================================================================

class TestExceptionHierarchy:
    def test_all_inherit_from_mpxj_error(self):
        assert issubclass(MpxjNotAvailableError, MpxjError)
        assert issubclass(MpxjFileError, MpxjError)
        assert issubclass(MpxjParseError, MpxjError)

    def test_mpxj_error_inherits_from_exception(self):
        assert issubclass(MpxjError, Exception)

    def test_errors_have_messages(self):
        e = MpxjFileError("test message")
        assert str(e) == "test message"


# ===========================================================================
# Test: JVM lifecycle
# ===========================================================================

class TestJVMLifecycle:
    @patch("src.mpxj_reader._jvm_started", False)
    def test_ensure_jvm_raises_when_jpype_missing(self):
        from src.mpxj_reader import _ensure_jvm

        with patch.dict(sys.modules, {"jpype": None}):
            with patch("builtins.__import__", side_effect=ImportError("no jpype")):
                with pytest.raises(MpxjNotAvailableError, match="jpype1 is not installed"):
                    _ensure_jvm()

    @patch("src.mpxj_reader._jvm_started", True)
    def test_ensure_jvm_noop_when_started(self):
        from src.mpxj_reader import _ensure_jvm
        # Should not raise
        _ensure_jvm()


# ===========================================================================
# Test: Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_task_with_all_none_fields(self):
        """Task where every optional getter returns None."""
        task = MagicMock()
        task.getUniqueID.return_value = 1
        task.getID.return_value = 1
        task.getName.return_value = None
        # All other getters return None
        for attr in [
            "getOutlineLevel", "getOutlineNumber", "getWBS", "getSummary",
            "getStart", "getFinish", "getDuration", "getActualStart",
            "getActualFinish", "getBaselineStart", "getBaselineFinish",
            "getBaselineDuration", "getPercentageComplete",
            "getPhysicalPercentComplete", "getConstraintType",
            "getConstraintDate", "getDeadline", "getPriority", "getType",
            "getMilestone", "getCritical", "getActive", "getTotalSlack",
            "getFreeSlack", "getCost", "getActualCost", "getBaselineCost",
            "getWork", "getActualWork", "getRemainingWork", "getNotes",
            "getCalendar", "getPredecessors", "getResourceAssignments",
        ]:
            getattr(task, attr).return_value = None

        result = _task_to_dict(task)
        # Should have identity fields even if values are None
        assert "unique_id" in result
        assert "id" in result

    def test_resource_with_calendar(self):
        res = _make_mock_resource()
        cal = MagicMock()
        cal.getName.return_value = "Custom Cal"
        res.getCalendar.return_value = cal
        result = _resource_to_dict(res)
        assert result["calendar_name"] == "Custom Cal"

    def test_assignment_with_no_resource(self):
        """Assignment where getResource returns None."""
        asn = _make_mock_assignment()
        asn.getResource.return_value = None
        result = _assignment_to_dict(asn)
        assert "resource_unique_id" not in result
        assert "resource_name" not in result

    def test_assignment_with_no_task(self):
        """Assignment where getTask returns None."""
        asn = _make_mock_assignment()
        asn.getTask.return_value = None
        result = _assignment_to_dict(asn)
        assert "task_unique_id" not in result
        assert "task_name" not in result

    @patch("src.mpxj_reader._open_project")
    def test_large_task_list_pagination(self, mock_open, tmp_mpp):
        """Verify pagination works correctly with many tasks."""
        tasks_list = [
            _make_mock_task(uid=i, task_id=i, name=f"Task {i}")
            for i in range(1, 501)
        ]
        mock_open.return_value = _make_mock_project(tasks=tasks_list)

        tasks, source = read_tasks(tmp_mpp)
        assert len(tasks) == 500
        assert source["count"] == 500

        # Paginate
        page, meta = paginate(tasks, offset=0, limit=50)
        assert len(page) == 50
        assert meta["truncated"] is True
        assert meta["next_offset"] == 50

    @patch("src.mpxj_reader._open_project")
    def test_parse_error_from_open(self, mock_open, tmp_mpp):
        """Verify MpxjParseError propagates from _open_project."""
        mock_open.side_effect = MpxjParseError("corrupt file")
        with pytest.raises(MpxjParseError, match="corrupt"):
            read_tasks(tmp_mpp)
