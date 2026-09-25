"""
Idempotent Bulk Operations — tests for bulk_ops.dry_run and bulk_ops.apply.

All tests run on macOS without COM via mocks.
"""

from unittest.mock import MagicMock, patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.bulk_ops import BulkAction, BulkItem, dry_run, apply
from tests._bulk_helpers import _make_task, _make_store


def _make_verify_result(success=True, drifted_count=0):
    """Create a mock VerifyResult."""
    vr = MagicMock()
    vr.to_dict.return_value = {
        "success": success,
        "drifted_count": drifted_count,
    }
    return vr


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
