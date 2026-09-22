"""
Tests for response size management (src/response.py).

Covers:
  - paginate(): slicing, truncation metadata, edge cases
  - strip_empty(): identity preservation, zero-is-meaningful, empty removal
  - format_response(): compact vs indented threshold
  - prepare_task_response(): full pipeline
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.response import (
    paginate, strip_empty, strip_empty_list, format_response,
    prepare_task_response, prepare_resource_response,
    DEFAULT_PAGE_LIMIT,
)


# ---------------------------------------------------------------------------
# paginate
# ---------------------------------------------------------------------------

class TestPaginate:
    def test_default_limit(self):
        items = list(range(300))
        page, meta = paginate(items)
        assert len(page) == DEFAULT_PAGE_LIMIT
        assert meta["total"] == 300
        assert meta["returned"] == DEFAULT_PAGE_LIMIT
        assert meta["truncated"] is True
        assert "next_offset" in meta
        assert meta["next_offset"] == DEFAULT_PAGE_LIMIT

    def test_no_truncation_when_fits(self):
        items = list(range(50))
        page, meta = paginate(items)
        assert len(page) == 50
        assert meta["total"] == 50
        assert "truncated" not in meta

    def test_offset(self):
        items = list(range(10))
        page, meta = paginate(items, offset=5, limit=3)
        assert page == [5, 6, 7]
        assert meta["offset"] == 5
        assert meta["returned"] == 3

    def test_limit_minus_one_returns_all(self):
        items = list(range(500))
        page, meta = paginate(items, limit=-1)
        assert len(page) == 500
        assert "truncated" not in meta

    def test_limit_none_returns_all(self):
        items = list(range(500))
        page, meta = paginate(items, limit=None)
        assert len(page) == 500

    def test_empty_list(self):
        page, meta = paginate([])
        assert page == []
        assert meta["total"] == 0
        assert meta["returned"] == 0

    def test_offset_beyond_end(self):
        items = list(range(5))
        page, meta = paginate(items, offset=10)
        assert page == []
        assert meta["returned"] == 0

    def test_truncation_includes_next_offset(self):
        items = list(range(300))
        page, meta = paginate(items, offset=0, limit=100)
        assert meta["truncated"] is True
        assert meta["next_offset"] == 100
        assert "hint" in meta

    def test_negative_offset_clamped_to_zero(self):
        items = list(range(10))
        page, meta = paginate(items, offset=-5, limit=3)
        assert page == [0, 1, 2]
        assert meta["offset"] == 0

    def test_offset_clamped_to_total(self):
        items = list(range(5))
        page, meta = paginate(items, offset=100, limit=3)
        assert page == []
        assert meta["offset"] == 5  # clamped to len(items)


# ---------------------------------------------------------------------------
# strip_empty
# ---------------------------------------------------------------------------

class TestStripEmpty:
    def test_identity_fields_always_kept(self):
        task = {"unique_id": 1, "id": 1, "name": "", "notes": ""}
        result = strip_empty(task)
        assert "unique_id" in result
        assert "id" in result
        assert "name" in result  # kept even though empty
        assert "notes" not in result  # dropped: empty string

    def test_zero_meaningful_fields_kept(self):
        task = {
            "unique_id": 1, "id": 1, "name": "Task",
            "percent_complete": 0,
            "duration_days": 0,
            "total_slack_days": 0,
            "free_slack_days": 0,
            "outline_level": 0,
            "remaining_duration_days": 0,
            "priority": 0,  # not meaningful — should be dropped
        }
        result = strip_empty(task)
        assert result["percent_complete"] == 0
        assert result["duration_days"] == 0
        assert result["total_slack_days"] == 0
        assert result["free_slack_days"] == 0
        assert result["outline_level"] == 0
        assert result["remaining_duration_days"] == 0
        assert "priority" not in result  # zero, not in meaningful set

    def test_none_dropped(self):
        task = {"unique_id": 1, "id": 1, "name": "T", "deadline": None}
        assert "deadline" not in strip_empty(task)

    def test_false_dropped(self):
        task = {"unique_id": 1, "id": 1, "name": "T", "critical": False}
        assert "critical" not in strip_empty(task)

    def test_truthy_kept(self):
        task = {"unique_id": 1, "id": 1, "name": "T",
                "critical": True, "notes": "Important"}
        result = strip_empty(task)
        assert result["critical"] is True
        assert result["notes"] == "Important"

    def test_strip_empty_list(self):
        tasks = [
            {"unique_id": 1, "id": 1, "name": "A", "notes": ""},
            {"unique_id": 2, "id": 2, "name": "B", "notes": "Has note"},
        ]
        result = strip_empty_list(tasks)
        assert "notes" not in result[0]
        assert result[1]["notes"] == "Has note"

    def test_reduction_ratio_on_sparse_task(self):
        """A typical sparse task should lose most of its fields."""
        sparse = {
            "unique_id": 42, "id": 5, "name": "Task 5",
            "outline_level": 1, "wbs": "", "summary": False,
            "milestone": False, "start": "2025-01-01 08:00:00",
            "finish": "2025-01-05 17:00:00", "duration_days": 5.0,
            "percent_complete": 0, "actual_start": None,
            "actual_finish": None, "remaining_duration_days": 5.0,
            "total_slack_days": 0, "free_slack_days": 0,
            "deadline": None, "priority": 500,
            "constraint_type": "ASAP", "constraint_date": None,
            "manual": False, "type": "FixedUnits",
            "predecessors": "", "resource_names": "",
            "notes": "", "critical": False, "active": True,
            "rag": "", "text1": "", "text2": "", "text3": "",
            "flag1": False, "flag2": False,
            "hyperlink": "", "hyperlink_text": "",
        }
        stripped = strip_empty(sparse)
        # Should have at most ~12 fields (identity + dates + meaningful zeros)
        assert len(stripped) < len(sparse)
        # At least 50% reduction
        assert len(stripped) <= len(sparse) * 0.5


# ---------------------------------------------------------------------------
# format_response
# ---------------------------------------------------------------------------

class TestFormatResponse:
    def test_small_response_indented(self):
        data = {"a": 1}
        result = format_response(data)
        assert "\n" in result  # indented
        assert json.loads(result) == data

    def test_large_response_compact(self):
        # Create data larger than threshold
        data = {"tasks": [{"name": f"task_{i}", "id": i} for i in range(200)]}
        result = format_response(data)
        assert "\n" not in result  # compact
        assert json.loads(result) == data

    def test_custom_threshold(self):
        data = {"key": "value"}
        # With threshold=0, everything is compact
        result = format_response(data, threshold=0)
        assert "\n" not in result

    def test_roundtrip_integrity(self):
        """Data survives serialize -> deserialize regardless of format."""
        data = {"tasks": [{"unique_id": i, "name": f"T{i}"} for i in range(50)]}
        for threshold in [0, 10000]:
            result = format_response(data, threshold=threshold)
            assert json.loads(result) == data


# ---------------------------------------------------------------------------
# prepare_task_response (full pipeline)
# ---------------------------------------------------------------------------

class TestPrepareTaskResponse:
    def _make_tasks(self, n):
        return [
            {"unique_id": i, "id": i, "name": f"Task {i}",
             "notes": "", "deadline": None, "critical": False,
             "percent_complete": 0, "outline_level": 1}
            for i in range(n)
        ]

    def test_pipeline_paginates(self):
        tasks = self._make_tasks(300)
        result = json.loads(prepare_task_response(tasks))
        assert result["pagination"]["total"] == 300
        assert result["pagination"]["returned"] == DEFAULT_PAGE_LIMIT
        assert result["pagination"]["truncated"] is True

    def test_pipeline_strips_empty(self):
        tasks = self._make_tasks(5)
        result = json.loads(prepare_task_response(tasks))
        for t in result["tasks"]:
            assert "notes" not in t  # empty string stripped
            assert "deadline" not in t  # None stripped
            assert "critical" not in t  # False stripped
            assert "unique_id" in t  # identity kept
            assert "percent_complete" in t  # meaningful zero kept

    def test_pipeline_no_strip(self):
        tasks = self._make_tasks(5)
        result = json.loads(prepare_task_response(tasks, strip=False))
        assert "notes" in result["tasks"][0]  # not stripped

    def test_pipeline_extra_fields(self):
        tasks = self._make_tasks(5)
        result = json.loads(prepare_task_response(
            tasks, extra={"project": "Test"}
        ))
        assert result["project"] == "Test"

    def test_resource_pipeline(self):
        resources = [
            {"unique_id": i, "id": i, "name": f"R{i}", "initials": "",
             "type": 0, "max_units": 1.0, "cost": 0, "task_count": 0}
            for i in range(5)
        ]
        result = json.loads(prepare_resource_response(resources))
        assert "pagination" in result
        assert "resources" in result
        assert result["pagination"]["total"] == 5
