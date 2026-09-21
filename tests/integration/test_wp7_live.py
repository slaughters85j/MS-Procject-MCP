"""
WP-7 Live Integration Tests: Idempotent Bulk Operations

Tests bulk update with dry-run/apply against real MS Project.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.bulk_ops import (
    BulkAction,
    BulkItem,
    dry_run,
    apply,
)
from src.task_store import TaskStore, init_store


class TestBulkOpsLive:
    """Real COM bulk operations."""

    def _setup_store(self, app):
        """Wire up a TaskStore for the active project."""
        return TaskStore(lambda: app.ActiveProject)

    def _get_work_task_uids(self, proj):
        """Get UniqueIDs of non-summary, non-milestone tasks."""
        uids = []
        for t in proj.Tasks:
            if t is not None and not t.Summary and not t.Milestone:
                uids.append(t.UniqueID)
        return uids

    def test_dry_run_shows_would_change(self, temp_mpp):
        app, proj, path = temp_mpp
        store = self._setup_store(app)
        uids = self._get_work_task_uids(proj)
        assert len(uids) >= 1

        items = [
            BulkItem(BulkAction.UPDATE, uids[0], {"Name": "DryRun Changed"}),
        ]
        result = dry_run(app, proj, items, store)
        assert result.mode == "dry_run"
        assert result.total == 1
        assert result.succeeded == 1
        assert result.items[0].status == "ok"

    def test_dry_run_skips_matching(self, temp_mpp):
        app, proj, path = temp_mpp
        store = self._setup_store(app)
        uids = self._get_work_task_uids(proj)

        # Read current name, then dry-run with same name
        task = store.resolve_task(uids[0]).task
        current_name = task.Name

        items = [
            BulkItem(BulkAction.UPDATE, uids[0], {"Name": current_name}),
        ]
        result = dry_run(app, proj, items, store)
        assert result.skipped == 1
        assert result.items[0].status == "skipped"

    def test_apply_writes_and_verifies(self, temp_mpp):
        app, proj, path = temp_mpp
        store = self._setup_store(app)
        uids = self._get_work_task_uids(proj)

        new_name = "WP7 Applied Name"
        items = [
            BulkItem(BulkAction.UPDATE, uids[0], {"Name": new_name}),
        ]
        result = apply(app, proj, items, store)
        assert result.mode == "apply"
        assert result.total == 1
        # Either succeeded or drifted (Project may recalc)
        assert result.succeeded + result.drifted >= 1
        assert result.failed == 0

        # Verify the write actually landed
        resolved = store.resolve_task(uids[0])
        assert resolved.task.Name == new_name

    def test_apply_idempotent(self, temp_mpp):
        """Applying the same update twice: second run skips."""
        app, proj, path = temp_mpp
        store = self._setup_store(app)
        uids = self._get_work_task_uids(proj)

        items = [
            BulkItem(BulkAction.UPDATE, uids[0], {"Text1": "Green"}),
        ]

        # First apply
        r1 = apply(app, proj, items, store)
        assert r1.succeeded + r1.drifted >= 1

        # Second apply — should skip (idempotent)
        r2 = apply(app, proj, items, store)
        assert r2.skipped == 1
        assert r2.succeeded == 0

    def test_apply_nonexistent_uid(self, temp_mpp):
        app, proj, path = temp_mpp
        store = self._setup_store(app)

        items = [
            BulkItem(BulkAction.UPDATE, 99999, {"Name": "Ghost"}),
        ]
        result = apply(app, proj, items, store)
        assert result.failed == 1
        assert "not found" in result.items[0].error.lower()

    def test_apply_multiple_items(self, temp_mpp):
        """Batch of 2+ items: all get individual results."""
        app, proj, path = temp_mpp
        store = self._setup_store(app)
        uids = self._get_work_task_uids(proj)
        assert len(uids) >= 2

        items = [
            BulkItem(BulkAction.UPDATE, uids[0], {"Text1": "Red"}),
            BulkItem(BulkAction.UPDATE, uids[1], {"Text1": "Amber"}),
        ]
        result = apply(app, proj, items, store)
        assert result.total == 2
        assert len(result.items) == 2
        # Each item has an individual status
        for ir in result.items:
            assert ir.status in ("ok", "skipped", "drifted")
