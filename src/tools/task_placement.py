"""
Task placement tools that need Project's clipboard (move, copy) plus recurring tasks.

MS Project has no COM method to move or copy a task, only row selection plus Cut/Copy/Paste.
Row numbers depend on the current view, so these tools show every task in ID order first and
verify that the selected rows are exactly the intended tasks before cutting or copying anything.
"""

import datetime
import json
from contextlib import contextmanager

from ..com_helpers import get_app, get_proj, _get_mpd, _find_task
from ..com_write import to_com_date, parse_iso, commit, batch_calc

MAX_COPIES = 20


def _subtree_uids(proj, task):
    """UniqueIDs of a task and, if it is a summary, every task below it."""
    uids, level, inside = [], task.OutlineLevel, False
    for t in proj.Tasks:
        if t is None:
            if inside:
                break
            continue
        if t.UniqueID == task.UniqueID:
            inside = True
        elif inside and t.OutlineLevel <= level:
            break
        if inside:
            uids.append(t.UniqueID)
    return uids


def _all_uids(proj):
    return {t.UniqueID for t in proj.Tasks if t is not None}


@contextmanager
def _rows_in_id_order(app, proj):
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


def _select_exactly(app, first_id, uids):
    """Select the rows for `uids` starting at task ID first_id; refuse if Project selected anything else."""
    if len(uids) > 1:
        app.SelectRow(Row=first_id, RowRelative=False, Height=len(uids) - 1)
    else:
        app.SelectRow(first_id, False)
    selection = app.ActiveSelection.Tasks
    got = [t.UniqueID for t in selection if t is not None] if selection else []
    if got != uids:
        raise RuntimeError(f"Selection check failed: expected UniqueIDs {uids} but the view selected {got}. "
                           "Nothing was changed. Switch the window to a task view (e.g. Gantt Chart) and retry.")


def register_task_placement_tools(mcp):
    """Register the move, copy and recurring-task tools on the FastMCP instance."""

    @mcp.tool()
    def move_task(unique_id: int, after_unique_id: int) -> str:
        """
        Reposition a task (with its subtasks) to directly after another task.

        MS Project can only move tasks by cut and paste, which assigns NEW UniqueIDs to the
        moved tasks (links are kept). The response maps old to new UniqueIDs; use the new ones.

        Args:
            unique_id:       Task UniqueID to move (required).
            after_unique_id: Place the moved task directly after this task's UniqueID (required).
        """
        app  = get_app()
        proj = get_proj(app)
        t = _find_task(proj, unique_id)
        after_t = _find_task(proj, after_unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})
        if after_t is None:
            return json.dumps({"error": f"Target task UniqueID {after_unique_id} not found."})
        moving = _subtree_uids(proj, t)
        if after_unique_id in moving:
            return json.dumps({"error": "Cannot move a task after itself or one of its own subtasks."})
        names = {u: _find_task(proj, u).Name for u in moving}

        with _rows_in_id_order(app, proj):
            _select_exactly(app, t.ID, moving)
            app.EditCut()
            before = _all_uids(proj)
            app.SelectRow(_find_task(proj, after_unique_id).ID + 1, False)
            try:
                app.EditPaste()
            except Exception:
                app.EditUndo()  # restore the cut rows before reporting the failure
                raise
        new_uids = sorted(_all_uids(proj) - before, key=lambda u: _find_task(proj, u).ID)
        commit(app, proj)
        moved = _find_task(proj, new_uids[0]) if new_uids else None
        return json.dumps({
            "status":         "moved",
            "old_unique_id":  unique_id,
            "unique_id":      moved.UniqueID if moved else None,
            "name":           moved.Name if moved else names[unique_id],
            "new_id":         moved.ID if moved else None,
            "uid_map":        dict(zip([str(u) for u in moving], new_uids)),
            "note":           "Cut/paste assigns new UniqueIDs; predecessor links are preserved.",
        }, indent=2)

    @mcp.tool()
    def copy_task_structure(source_unique_id: int, copies: int = 1) -> str:
        """
        Duplicate a task subtree (reusable programme templates), appending each copy at the end.

        Args:
            source_unique_id: UniqueID of the task to copy (and its children if summary).
            copies:           Number of copies to create, 1-20 (default 1).
        """
        if not 1 <= copies <= MAX_COPIES:
            return json.dumps({"error": f"copies must be between 1 and {MAX_COPIES}."})
        app  = get_app()
        proj = get_proj(app)
        source = _find_task(proj, source_unique_id)
        if source is None:
            return json.dumps({"error": f"Task UniqueID {source_unique_id} not found."})
        uids = _subtree_uids(proj, source)

        all_copies = []
        with _rows_in_id_order(app, proj):
            _select_exactly(app, source.ID, uids)
            app.EditCopy()
            for _ in range(copies):
                before = _all_uids(proj)
                app.SelectRow(proj.Tasks.Count + 1, False)
                app.EditPaste()
                new = sorted(_all_uids(proj) - before, key=lambda u: _find_task(proj, u).ID)
                all_copies.append([{"unique_id": u, "name": _find_task(proj, u).Name} for u in new])
        commit(app, proj)
        return json.dumps({"status": "copied", "source_name": source.Name,
                           "copies": len(all_copies), "copied_tasks": all_copies}, indent=2)

    @mcp.tool()
    def add_recurring_task(
        name:            str,
        recurrence_type: str = "weekly",
        start_date:      str = "",
        end_date:        str = "",
        duration_days:   float = 1,
        day_of_week:     int = 2,
    ) -> str:
        """
        Add a recurring task: a top-level summary with one subtask per occurrence.

        Args:
            name:            Task name.
            recurrence_type: 'daily' (working days only), 'weekly', 'monthly', or 'yearly'.
            start_date:      Recurrence range start (YYYY-MM-DD).
            end_date:        Recurrence range end (YYYY-MM-DD), not before start_date.
            duration_days:   Duration of each occurrence in working days (default 1).
            day_of_week:     For weekly: 1=Sun, 2=Mon, ..., 7=Sat (default 2=Monday).
        """
        from dateutil.rrule import rrule, DAILY, WEEKLY, MONTHLY, YEARLY
        freq = {"daily": DAILY, "weekly": WEEKLY, "monthly": MONTHLY, "yearly": YEARLY}.get(recurrence_type.lower())
        if freq is None:
            return json.dumps({"error": f"Unknown recurrence_type '{recurrence_type}'. Use: daily, weekly, monthly, yearly."})
        if not name.strip():
            return json.dumps({"error": "name is required."})
        if not 1 <= day_of_week <= 7:
            return json.dumps({"error": "day_of_week must be 1 (Sunday) through 7 (Saturday)."})
        if duration_days <= 0:
            return json.dumps({"error": "duration_days must be greater than 0."})
        sd, _ = parse_iso(start_date, "start_date")
        ed, _ = parse_iso(end_date, "end_date")
        if ed < sd:
            return json.dumps({"error": "end_date is before start_date."})

        app  = get_app()
        proj = get_proj(app)
        # dateutil weekday: 0=Mon..6=Sun; Project: 1=Sun..7=Sat
        byday = (day_of_week - 2) % 7
        dates = list(rrule(freq, dtstart=sd, until=ed, byweekday=byday)) if freq == WEEKLY \
            else list(rrule(freq, dtstart=sd, until=ed))
        if freq == DAILY:
            cal = proj.Calendar
            dates = [d for d in dates
                     if cal.Period(d.replace(tzinfo=datetime.timezone.utc)).Working]
        if not dates:
            return json.dumps({"error": "No occurrences fall in the given range."})

        duration = round(duration_days * _get_mpd(proj))
        with batch_calc(app):
            summary = proj.Tasks.Add(name)
            summary.OutlineLevel = 1
            occurrences = []
            for i, d in enumerate(dates, 1):
                occ = proj.Tasks.Add(f"{name} #{i}")
                occ.OutlineLevel = 2  # explicit level: never inherit the previous row's level
                occ.Duration = duration
                occ.Start = to_com_date(proj, d.strftime("%Y-%m-%d"))
                occurrences.append(occ.UniqueID)
        commit(app, proj)
        return json.dumps({
            "status": "created", "name": name, "unique_id": summary.UniqueID,
            "recurrence_type": recurrence_type.lower(), "occurrences": len(occurrences),
            "occurrence_unique_ids": occurrences, "start": start_date, "end": end_date,
        }, indent=2)
