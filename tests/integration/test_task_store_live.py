"""
Live Integration Tests: COM Proxy Refresh (TaskStore)

Tests TaskStore resolution against real MS Project COM objects.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.task_store import TaskStore, StoreEvent


class TestTaskStoreResolution:
    """Real COM task resolution by UniqueID."""

    def _make_store(self, app):
        """Create a TaskStore backed by the real COM project."""
        return TaskStore(lambda: app.ActiveProject)

    def test_resolve_existing_task(self, temp_mpp):
        app, proj, path = temp_mpp
        store = self._make_store(app)

        # Get a known UniqueID
        first_task = None
        for t in proj.Tasks:
            if t is not None and not t.Summary:
                first_task = t
                break
        assert first_task is not None

        uid = first_task.UniqueID
        result = store.resolve_task(uid)
        assert result.found
        assert result.task is not None
        assert result.task.UniqueID == uid
        assert result.error is None

    def test_resolve_nonexistent_uid(self, temp_mpp):
        app, proj, path = temp_mpp
        store = self._make_store(app)

        result = store.resolve_task(99999)
        assert not result.found
        assert result.task is None
        assert "not found" in result.error.lower()

    def test_resolve_after_insert(self, temp_mpp):
        """New task is resolvable immediately (no stale cache)."""
        app, proj, path = temp_mpp
        store = self._make_store(app)

        new_task = proj.Tasks.Add("TaskStore New Task")
        new_uid = new_task.UniqueID
        store.invalidate(StoreEvent.INSERT)

        result = store.resolve_task(new_uid)
        assert result.found
        assert result.task.Name == "TaskStore New Task"

    def test_resolve_after_save(self, temp_mpp):
        """Tasks remain resolvable after a save operation."""
        app, proj, path = temp_mpp
        store = self._make_store(app)

        # Get a UID before save
        task = None
        for t in proj.Tasks:
            if t is not None and not t.Summary:
                task = t
                break
        uid = task.UniqueID

        app.FileSave()
        store.invalidate(StoreEvent.SAVE)

        result = store.resolve_task(uid)
        assert result.found
        assert result.task.UniqueID == uid

    def test_get_all_tasks(self, temp_mpp):
        app, proj, path = temp_mpp
        store = self._make_store(app)

        tasks, error = store.get_all_tasks()
        assert error is None
        assert len(tasks) >= 1
        # All returned tasks should be non-None
        for t in tasks:
            assert t is not None

    def test_store_stats(self, temp_mpp):
        app, proj, path = temp_mpp
        store = self._make_store(app)

        store.resolve_task(1)
        store.invalidate(StoreEvent.MANUAL)
        stats = store.get_stats()
        assert stats["resolve_count"] >= 1
        assert stats["invalidation_count"] >= 1

    def test_resolve_resource(self, temp_mpp):
        """resolve_resource works (may find none if no resources assigned)."""
        app, proj, path = temp_mpp
        store = self._make_store(app)

        result = store.resolve_resource(99999)
        assert not result.found
        assert "not found" in result.error.lower()
