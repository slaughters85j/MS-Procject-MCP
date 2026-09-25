"""
Shared mock builders (COM tasks, TaskStore) for the bulk operations tests.
"""

from unittest.mock import MagicMock


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
