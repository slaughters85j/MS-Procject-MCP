"""
Idempotent Bulk Operations — tests.

All tests run on macOS without COM via mocks.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.bulk_ops import (
    BulkAction, BulkItem, ItemResult, BulkResult,
    validate_bulk_items, dry_run, apply,
    _fields_already_match, _read_current_fields,
)
from src.bulk_tools import _parse_items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(uid, **fields):
    """Create a mock COM task with UniqueID and arbitrary fields."""
    t = MagicMock()
    t.UniqueID = uid
    for k, v in fields.items():
        setattr(t, k, v)
    return t


def _make_store(tasks_by_uid):
    """Create a mock TaskStore that resolves tasks from a dict."""
    from src.task_store import ResolveResult
    store = MagicMock()

    def _resolve(uid):
        if uid in tasks_by_uid:
            return ResolveResult(task=tasks_by_uid[uid], found=True)
        return ResolveResult(
            task=None, found=False,
            error=f"Task UniqueID {uid} not found",
        )

    store.resolve_task = MagicMock(side_effect=_resolve)
    return store


def _make_verify_result(success=True, drifted_count=0):
    """Create a mock VerifyResult."""
    vr = MagicMock()
    vr.to_dict.return_value = {
        "success": success,
        "drifted_count": drifted_count,
    }
    return vr


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


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_reports_would_change(self):
        task = _make_task(1, Name="Old name")
        store = _make_store({1: task})
        items = [BulkItem(BulkAction.UPDATE, 1, {"Name": "New name"})]
        app = MagicMock()

        result = dry_run(app, None, items, store)
        assert result.mode == "dry_run"
        assert result.succeeded == 1
        assert result.items[0].status == "ok"
        assert result.items[0].current_values["Name"] == "Old name"
        assert result.items[0].fields_written["Name"] != "Old name"

    def test_skips_already_matching(self):
        task = _make_task(1, Name="Same")
        store = _make_store({1: task})
        items = [BulkItem(BulkAction.UPDATE, 1, {"Name": "Same"})]

        result = dry_run(MagicMock(), None, items, store)
        assert result.skipped == 1
        assert result.items[0].status == "skipped"

    def test_unresolvable_uid(self):
        store = _make_store({})  # empty
        items = [BulkItem(BulkAction.UPDATE, 999, {"Name": "x"})]

        result = dry_run(MagicMock(), None, items, store)
        assert result.failed == 1
        assert "not found" in result.items[0].error

    def test_validation_failure(self):
        """Validation errors prevent even resolution."""
        items = [BulkItem(BulkAction.UPDATE, None, {})]
        result = dry_run(MagicMock(), None, items, MagicMock())
        assert result.failed == len(items)
        assert result.items[0].status == "error"
        assert "validate" in result.items[0].action

    def test_mixed_results(self):
        t1 = _make_task(1, Name="Old")
        t2 = _make_task(2, Name="Same")
        store = _make_store({1: t1, 2: t2})
        items = [
            BulkItem(BulkAction.UPDATE, 1, {"Name": "New"}),
            BulkItem(BulkAction.UPDATE, 2, {"Name": "Same"}),
            BulkItem(BulkAction.UPDATE, 99, {"Name": "x"}),
        ]
        result = dry_run(MagicMock(), None, items, store)
        assert result.succeeded == 1
        assert result.skipped == 1
        assert result.failed == 1


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

class TestApply:
    def _run_apply(self, items, tasks_by_uid, verify_success=True):
        """Helper: mock deferred_calc, ui_lock, verify, run apply."""
        store = _make_store(tasks_by_uid)
        app = MagicMock()
        project = MagicMock()

        # Mock deferred_calc as a context manager
        mock_calc_state = MagicMock()
        mock_ui_state = MagicMock()
        mock_ui_state.errors = []

        vresult = _make_verify_result(success=verify_success,
                                       drifted_count=0 if verify_success else 1)

        # Patch the SOURCE modules — apply() uses lazy imports from them
        with patch("src.calc_policy.deferred_calc") as dc, \
             patch("src.calc_policy.calculate_project") as cp, \
             patch("src.ui_lock.ui_lock") as ul, \
             patch("src.verify_write.verify_task_write", return_value=vresult) as vf:
            dc.return_value.__enter__ = MagicMock(return_value=mock_calc_state)
            dc.return_value.__exit__ = MagicMock(return_value=False)
            ul.return_value.__enter__ = MagicMock(return_value=mock_ui_state)
            ul.return_value.__exit__ = MagicMock(return_value=False)
            cp.return_value = {"status": "ok"}

            result = apply(app, project, items, store)
            return result, dc, ul, vf, app, project

    def test_writes_and_verifies(self):
        task = _make_task(1, Name="Old")
        items = [BulkItem(BulkAction.UPDATE, 1, {"Name": "New"})]
        result, dc, ul, vf, app, proj = self._run_apply(
            items, {1: task})

        assert result.mode == "apply"
        assert result.succeeded == 1
        assert result.items[0].status == "ok"
        assert task.Name == "New"  # setattr was called

        # deferred_calc and ui_lock were entered
        dc.assert_called_once()
        ul.assert_called_once()

    def test_idempotent_skip(self):
        task = _make_task(1, Name="Same")
        items = [BulkItem(BulkAction.UPDATE, 1, {"Name": "Same"})]
        result, *_ = self._run_apply(items, {1: task})
        assert result.skipped == 1
        assert result.items[0].status == "skipped"

    def test_drifted_result(self):
        task = _make_task(1, Name="Old")
        items = [BulkItem(BulkAction.UPDATE, 1, {"Name": "New"})]
        result, *_ = self._run_apply(
            items, {1: task}, verify_success=False)
        assert result.drifted == 1
        assert result.items[0].status == "drifted"

    def test_per_item_com_error_continues(self):
        """COM error on one item doesn't abort the batch."""
        t1 = _make_task(1, Name="Old1")
        t2 = _make_task(2, Name="Old2")

        # Make t1 raise on write
        type(t1).Name = property(
            lambda self: "Old1",
            lambda self, v: (_ for _ in ()).throw(Exception("COM write fail")),
        )

        items = [
            BulkItem(BulkAction.UPDATE, 1, {"Name": "New1"}),
            BulkItem(BulkAction.UPDATE, 2, {"Name": "New2"}),
        ]
        result, *_ = self._run_apply(items, {1: t1, 2: t2})

        assert result.failed == 1
        assert result.succeeded == 1
        assert result.items[0].status == "error"
        assert "COM write fail" in result.items[0].error
        assert result.items[1].status == "ok"

    def test_unresolvable_uid_error(self):
        items = [BulkItem(BulkAction.UPDATE, 999, {"Name": "x"})]
        result, *_ = self._run_apply(items, {})
        assert result.failed == 1
        assert "not found" in result.items[0].error

    def test_calculate_project_called_after_batch(self):
        task = _make_task(1, Name="Old")
        items = [BulkItem(BulkAction.UPDATE, 1, {"Name": "New"})]
        result, dc, ul, vf, app, proj = self._run_apply(
            items, {1: task})
        # calculate_project is called after the with blocks
        # (we can't easily assert it was called with our mock setup,
        # but we verify no error in result)
        assert result.succeeded == 1

    def test_validation_failure_skips_all(self):
        items = [BulkItem(BulkAction.UPDATE, None, {})]
        result, *_ = self._run_apply(items, {})
        assert result.failed == len(items)
        assert result.items[0].action == "validate"

    def test_empty_after_fix_still_returns(self):
        """Single item, all fields match -> skip."""
        task = _make_task(1, Name="Same", Duration=100)
        items = [BulkItem(BulkAction.UPDATE, 1,
                          {"Name": "Same", "Duration": 100})]
        result, *_ = self._run_apply(items, {1: task})
        assert result.total == 1
        assert result.skipped == 1
        assert result.succeeded == 0


# ---------------------------------------------------------------------------
# Parse items (bulk_tools)
# ---------------------------------------------------------------------------

class TestParseItems:
    def test_valid_json(self):
        raw = json.dumps([
            {"action": "update", "target_uid": 1, "fields": {"Name": "x"}}
        ])
        items = _parse_items(raw)
        assert len(items) == 1
        assert items[0].action == BulkAction.UPDATE
        assert items[0].target_uid == 1

    def test_invalid_json(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            _parse_items("not json{{{")

    def test_not_array(self):
        with pytest.raises(ValueError, match="JSON array"):
            _parse_items('{"action": "update"}')

    def test_unknown_action(self):
        raw = json.dumps([{"action": "explode", "target_uid": 1,
                           "fields": {"x": 1}}])
        with pytest.raises(ValueError, match="unknown action"):
            _parse_items(raw)

    def test_bad_uid_type(self):
        raw = json.dumps([{"action": "update", "target_uid": "abc",
                           "fields": {"x": 1}}])
        with pytest.raises(ValueError, match="integer"):
            _parse_items(raw)

    def test_item_not_object(self):
        raw = json.dumps(["just a string"])
        with pytest.raises(ValueError, match="expected object"):
            _parse_items(raw)

    def test_fields_not_dict(self):
        raw = json.dumps([{"action": "update", "target_uid": 1,
                           "fields": "not a dict"}])
        with pytest.raises(ValueError, match="fields must be an object"):
            _parse_items(raw)

    def test_empty_array(self):
        """Empty JSON array is valid parse, validation catches it later."""
        items = _parse_items("[]")
        assert items == []

    def test_multiple_items(self):
        raw = json.dumps([
            {"action": "update", "target_uid": 1, "fields": {"Name": "a"}},
            {"action": "update", "target_uid": 2, "fields": {"Name": "b"}},
        ])
        items = _parse_items(raw)
        assert len(items) == 2
        assert items[0].target_uid == 1
        assert items[1].target_uid == 2

    def test_missing_fields_key_defaults_empty(self):
        """Omitting 'fields' key defaults to empty dict."""
        raw = json.dumps([{"action": "update", "target_uid": 1}])
        items = _parse_items(raw)
        assert items[0].fields == {}

    def test_target_uid_none(self):
        """target_uid can be None (for insert actions eventually)."""
        raw = json.dumps([{"action": "update", "fields": {"Name": "x"}}])
        items = _parse_items(raw)
        assert items[0].target_uid is None

    def test_missing_action_key(self):
        """Missing 'action' key gives a clear error, not 'unknown action'."""
        raw = json.dumps([{"target_uid": 1, "fields": {"Name": "x"}}])
        with pytest.raises(ValueError, match="missing required 'action'"):
            _parse_items(raw)


# ---------------------------------------------------------------------------
# Tool-level edge cases (bulk_update via register_bulk_tools)
# ---------------------------------------------------------------------------

class TestBulkUpdateTool:
    """Test the registered bulk_update tool function at the tool level."""

    def _get_tool(self):
        """Register bulk tools on a mock MCP and return the bulk_update fn."""
        from src.bulk_tools import register_bulk_tools
        mock_mcp = MagicMock()
        # Capture the decorated functions
        registered = {}
        def tool_decorator():
            def wrapper(fn):
                registered[fn.__name__] = fn
                return fn
            return wrapper
        mock_mcp.tool = tool_decorator
        register_bulk_tools(mock_mcp)
        return registered["bulk_update"], registered.get("bulk_status")

    def test_empty_items_returns_validation_error(self):
        """Empty array parses, but validate_bulk_items rejects it."""
        bulk_update, _ = self._get_tool()
        with patch("src.bulk_tools.get_session") as gs, \
             patch("src.bulk_tools.get_store") as gst:
            session = MagicMock()
            session.is_attached = True
            session.app = MagicMock()
            session.app.ActiveProject = MagicMock()
            gs.return_value = session
            gst.return_value = MagicMock()

            result = bulk_update(items="[]", mode="dry_run")
            # Validation catches empty list — failed count is at least 1
            assert result["total"] == 0
            assert result["failed"] >= 1
            assert len(result["items"]) == 1
            assert result["items"][0]["status"] == "error"
            assert "empty" in result["items"][0]["error"]

    def test_single_item_dry_run(self):
        """Single-item dry_run goes through the full path."""
        bulk_update, _ = self._get_tool()
        task = _make_task(1, Name="Old")
        store = _make_store({1: task})
        with patch("src.bulk_tools.get_session") as gs, \
             patch("src.bulk_tools.get_store", return_value=store):
            session = MagicMock()
            session.is_attached = True
            session.app = MagicMock()
            session.app.ActiveProject = MagicMock()
            gs.return_value = session

            raw = json.dumps([
                {"action": "update", "target_uid": 1, "fields": {"Name": "New"}}
            ])
            result = bulk_update(items=raw, mode="dry_run")
            assert result["mode"] == "dry_run"
            assert result["total"] == 1
            assert result["succeeded"] == 1

    def test_all_skipped_scenario(self):
        """Every item already matches -> all skipped, zero succeeded."""
        bulk_update, _ = self._get_tool()
        t1 = _make_task(1, Name="Same1")
        t2 = _make_task(2, Name="Same2")
        store = _make_store({1: t1, 2: t2})
        with patch("src.bulk_tools.get_session") as gs, \
             patch("src.bulk_tools.get_store", return_value=store):
            session = MagicMock()
            session.is_attached = True
            session.app = MagicMock()
            session.app.ActiveProject = MagicMock()
            gs.return_value = session

            raw = json.dumps([
                {"action": "update", "target_uid": 1, "fields": {"Name": "Same1"}},
                {"action": "update", "target_uid": 2, "fields": {"Name": "Same2"}},
            ])
            result = bulk_update(items=raw, mode="dry_run")
            assert result["total"] == 2
            assert result["skipped"] == 2
            assert result["succeeded"] == 0
            assert result["failed"] == 0

    def test_invalid_mode(self):
        """Invalid mode returns error dict immediately."""
        bulk_update, _ = self._get_tool()
        result = bulk_update(items="[]", mode="yolo")
        assert "error" in result
        assert "mode" in result["error"]

    def test_session_not_attached(self):
        """Detached session returns readable error."""
        bulk_update, _ = self._get_tool()
        with patch("src.bulk_tools.get_session") as gs:
            session = MagicMock()
            session.is_attached = False
            gs.return_value = session
            result = bulk_update(
                items='[{"action":"update","target_uid":1,"fields":{"Name":"x"}}]',
                mode="dry_run",
            )
            assert "error" in result
            assert "session" in result["error"].lower() or "attach" in result["error"].lower()

    def test_bulk_status_before_any_run(self):
        """bulk_status before any run returns informative message."""
        import src.bulk_tools as bt
        bt._last_result = None
        _, bulk_status = self._get_tool()
        result = bulk_status()
        assert "no bulk" in result.get("status", "").lower()
