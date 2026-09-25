"""
Verified task selection in MS Project's view.

A few operations have no object-level COM API and act on the view selection: cut/copy/paste
(move_task, copy_task_structure) and BaselineSave/BaselineClear for specific tasks. Row numbers
depend on the view's filter, grouping, sort and collapsed outline, so these helpers first show
every task in ID order and then refuse to proceed unless the selection is exactly the tasks asked for.
"""

from contextlib import contextmanager

from .com_write import invoke_positional


@contextmanager
def rows_in_id_order(app, proj):
    """Show all tasks, ungrouped and in ID order, so view row N is task ID N. Restores filter and group."""
    old_filter, old_group = proj.CurrentFilter, proj.CurrentGroup
    app.FilterApply("All Tasks")
    app.GroupApply("No Group")
    app.OutlineShowAllTasks()
    app.Sort(Key1="ID", Ascending1=True, Renumber=False)
    try:
        yield
    finally:
        for apply, name in ((app.FilterApply, old_filter), (app.GroupApply, old_group)):
            try:
                if name:
                    apply(name)
            except Exception:
                pass


def _selected_uids(app):
    selection = app.ActiveSelection.Tasks
    return [t.UniqueID for t in selection if t is not None] if selection else []


def _refuse(expected, got):
    raise RuntimeError(f"Selection check failed: expected UniqueIDs {expected} but the view selected {got}. "
                       "Nothing was changed. Switch the window to a task view (e.g. Gantt Chart) and retry.")


def select_block(app, first_id, uids):
    """Select the contiguous rows for `uids` starting at task ID first_id, verified."""
    invoke_positional(app, "SelectRow", first_id, False, len(uids) - 1 if len(uids) > 1 else None)
    got = _selected_uids(app)
    if got != uids:
        _refuse(uids, got)


def select_tasks(proj, app, uids):
    """Select any set of tasks (rows need not be contiguous), verified. Call inside rows_in_id_order."""
    by_uid = {t.UniqueID: t for t in proj.Tasks if t is not None}
    missing = [u for u in uids if u not in by_uid]
    if missing:
        raise ValueError(f"Task UniqueID(s) not found: {missing}")
    ordered = sorted(set(uids), key=lambda u: by_uid[u].ID)
    for i, uid in enumerate(ordered):
        # Row, RowRelative, Height, Extend, Add: Add is ignored when passed by name.
        invoke_positional(app, "SelectRow", by_uid[uid].ID, False, None, None, i > 0)
    got = _selected_uids(app)
    if sorted(got) != sorted(ordered):
        _refuse(ordered, got)
