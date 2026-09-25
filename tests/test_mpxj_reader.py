"""
Unit tests for the mpxj read_* API and entity conversion edge cases.
All tests use mocked mpxj/jpype, so no JVM or Java is required.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.mpxj_jvm import MpxjFileError, MpxjParseError
from src.mpxj_convert import _assignment_to_dict, _resource_to_dict, _task_to_dict
from src.mpxj_reader import (
    _source_metadata,
    read_assignments,
    read_calendars,
    read_project_info,
    read_resources,
    read_tasks,
)
from src.response import paginate
from tests.mpxj_fakes import (
    _make_mock_task,
    _make_mock_resource,
    _make_mock_assignment,
    _make_mock_calendar,
    _make_mock_project,
)


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


class TestReadAssignments:
    @patch("src.mpxj_reader._open_project")
    def test_reads_assignments(self, mock_open, tmp_mpp):
        asn = _make_mock_assignment()
        mock_open.return_value = _make_mock_project(assignments=[asn])

        assignments, source = read_assignments(tmp_mpp)
        assert len(assignments) == 1
        assert source["entity_type"] == "assignments"


class TestReadCalendars:
    @patch("src.mpxj_reader._open_project")
    def test_reads_calendars(self, mock_open, tmp_mpp):
        cal = _make_mock_calendar(uid=1, name="Standard")
        mock_open.return_value = _make_mock_project(calendars=[cal])

        calendars, source = read_calendars(tmp_mpp)
        assert len(calendars) == 1
        assert calendars[0]["name"] == "Standard"
        assert source["entity_type"] == "calendars"


class TestReadProjectInfo:
    @patch("src.mpxj_reader._open_project")
    def test_reads_project_info(self, mock_open, tmp_mpp):
        mock_open.return_value = _make_mock_project()

        info, source = read_project_info(tmp_mpp)
        assert info["project_title"] == "Test Project"
        assert info["author"] == "John"
        assert source["entity_type"] == "project_info"


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
