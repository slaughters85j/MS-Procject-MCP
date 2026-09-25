"""
Idempotent Bulk Operations — tests for the bulk_ops models, validation
and field-comparison helpers.

All tests run on macOS without COM via mocks.
"""

import pytest
from unittest.mock import MagicMock

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.bulk_ops import (
    BulkAction, BulkItem, ItemResult, BulkResult,
    validate_bulk_items,
    _fields_already_match, _read_current_fields,
)
from tests._bulk_helpers import _make_task


# ---------------------------------------------------------------------------
# BulkAction enum
# ---------------------------------------------------------------------------

class TestBulkAction:
    def test_values(self):
        assert BulkAction.UPDATE.value == "update"
        assert BulkAction.INSERT.value == "insert"
        assert BulkAction.DELETE.value == "delete"

    def test_from_string(self):
        assert BulkAction("update") == BulkAction.UPDATE

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            BulkAction("nope")


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------

class TestBulkItem:
    def test_to_dict(self):
        item = BulkItem(
            action=BulkAction.UPDATE,
            target_uid=42,
            fields={"Name": "Fix the bug"},
        )
        d = item.to_dict()
        assert d["action"] == "update"
        assert d["target_uid"] == 42
        assert d["fields"]["Name"] == "Fix the bug"


class TestItemResult:
    def test_to_dict_ok(self):
        ir = ItemResult(unique_id=1, action="update", status="ok",
                        fields_written={"Name": "x"})
        d = ir.to_dict()
        assert d["status"] == "ok"
        assert d["fields_written"] == {"Name": "x"}
        assert "error" not in d

    def test_to_dict_error(self):
        ir = ItemResult(unique_id=1, action="update", status="error",
                        error="COM exploded")
        d = ir.to_dict()
        assert d["error"] == "COM exploded"

    def test_to_dict_skipped_minimal(self):
        ir = ItemResult(unique_id=1, action="update", status="skipped")
        d = ir.to_dict()
        assert d["status"] == "skipped"
        assert "fields_written" not in d
        assert "verification" not in d
        assert "error" not in d


class TestBulkResult:
    def test_to_dict(self):
        br = BulkResult(mode="dry_run", total=2, succeeded=1, skipped=1)
        d = br.to_dict()
        assert d["mode"] == "dry_run"
        assert d["total"] == 2
        assert d["items"] == []

    def test_to_dict_with_items(self):
        ir = ItemResult(unique_id=1, action="update", status="ok")
        br = BulkResult(mode="apply", total=1, succeeded=1, items=[ir])
        d = br.to_dict()
        assert len(d["items"]) == 1
        assert d["items"][0]["unique_id"] == 1


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_empty_list(self):
        errs = validate_bulk_items([])
        assert any("empty" in e for e in errs)

    def test_valid_update(self):
        items = [BulkItem(BulkAction.UPDATE, 1, {"Name": "x"})]
        assert validate_bulk_items(items) == []

    def test_missing_uid_for_update(self):
        items = [BulkItem(BulkAction.UPDATE, None, {"Name": "x"})]
        errs = validate_bulk_items(items)
        assert any("target_uid" in e for e in errs)

    def test_empty_fields(self):
        items = [BulkItem(BulkAction.UPDATE, 1, {})]
        errs = validate_bulk_items(items)
        assert any("fields" in e for e in errs)

    def test_unimplemented_action(self):
        items = [BulkItem(BulkAction.INSERT, None, {"Name": "x"})]
        errs = validate_bulk_items(items)
        assert any("not yet implemented" in e for e in errs)

    def test_multiple_errors(self):
        items = [
            BulkItem(BulkAction.UPDATE, None, {}),  # 2 errors
        ]
        errs = validate_bulk_items(items)
        assert len(errs) == 2  # missing uid + empty fields


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestFieldsAlreadyMatch:
    def test_match(self):
        task = _make_task(1, Name="Fix bug", Duration=480)
        assert _fields_already_match(task, {"Name": "Fix bug", "Duration": 480})

    def test_mismatch(self):
        task = _make_task(1, Name="Fix bug")
        assert not _fields_already_match(task, {"Name": "New name"})

    def test_read_error_returns_false(self):
        task = MagicMock()
        task.Name = property(lambda self: (_ for _ in ()).throw(Exception("boom")))
        type(task).Name = property(lambda self: (_ for _ in ()).throw(Exception("boom")))
        assert not _fields_already_match(task, {"Name": "x"})


class TestReadCurrentFields:
    def test_reads_values(self):
        task = _make_task(1, Name="hello", Duration=100)
        result = _read_current_fields(task, {"Name": "x", "Duration": 0})
        assert result["Name"] == "hello"
        assert result["Duration"] == 100

    def test_read_error_captured(self):
        task = MagicMock(spec=[])  # no attributes
        result = _read_current_fields(task, {"Bogus": "x"})
        assert "<read error:" in result["Bogus"]
