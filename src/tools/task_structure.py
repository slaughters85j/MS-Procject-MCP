"""
Task creation, deletion, copying, recurrence, and outline placement.
"""

import json

from ..com_helpers import get_app, get_proj, _get_mpd, _parse_date, _find_task
from ..guards import is_dry_run, dry_run_response


def register_task_structure_tools(mcp):
    """Register the task structure tools on the FastMCP instance."""

    @mcp.tool()
    def add_task(
        name:          str,
        outline_level: int  = 1,
        start:         str  = "",
        finish:        str  = "",
        duration_days: int  = 1,
        milestone:     bool = False,
        notes:         str  = "",
        resource:      str  = "",
        rag:           str  = "",
        after_unique_id: int = 0,
    ) -> str:
        """
        Add a new task to the active project.

        Args:
            name:            Task name (required).
            outline_level:   WBS level (1 = top-level, 2 = sub-task, etc.).
            start:           Start date YYYY-MM-DD (optional).
            finish:          Finish date YYYY-MM-DD (optional).
            duration_days:   Duration in days (default 1).
            milestone:       True to create as a milestone.
            notes:           Free-text notes.
            resource:        Resource name to assign.
            rag:             RAG status stored in Text1.
            after_unique_id: Insert after this task's UniqueID (0 = append at end).
        """
        app  = get_app()
        proj = get_proj(app)
        mpd  = _get_mpd(proj)

        app.Calculation = 0

        try:
            task = proj.Tasks.Add(name)
            task.OutlineLevel  = outline_level
            task.Milestone     = milestone
            if milestone:
                task.Duration = 0
            else:
                task.Duration = max(duration_days, 1) * mpd

            if start:
                task.Start = _parse_date(start)
            if finish:
                task.Finish = _parse_date(finish)
            if notes:
                task.Notes = notes
            if resource:
                task.ResourceNames = resource
            if rag:
                task.Text1 = rag

        finally:
            app.CalculateProject()
            app.Calculation = -1

        app.FileSave()
        return json.dumps({
            "status":    "created",
            "unique_id": task.UniqueID,
            "id":        task.ID,
            "name":      task.Name,
        }, indent=2)


    @mcp.tool()
    def bulk_add_tasks(tasks_json: str) -> str:
        """
        Add multiple tasks in one call. Critical for roadmap generation.
        Suspends auto-calc for performance. Tasks are added sequentially;
        outline_level controls WBS hierarchy.

        Args:
            tasks_json: JSON string — list of task objects with fields:
                name (required), outline_level (default 1), start, finish,
                duration_days (default 1), milestone (bool), resource,
                rag, text2, text3, notes, manual (bool).
                Example: '[{"name": "Phase 1", "outline_level": 1},
                           {"name": "Task A", "outline_level": 2, "start": "2026-04-01"}]'
        """
        tasks = json.loads(tasks_json)
        app   = get_app()
        proj  = get_proj(app)
        mpd   = _get_mpd(proj)

        app.Calculation = 0
        created = []

        try:
            for item in tasks:
                t = proj.Tasks.Add(item["name"])
                t.OutlineLevel = item.get("outline_level", 1)
                t.Milestone = item.get("milestone", False)

                dur = item.get("duration_days", 1)
                if t.Milestone:
                    t.Duration = 0
                else:
                    t.Duration = max(dur, 1) * mpd

                if item.get("start"):
                    t.Start = _parse_date(item["start"])
                if item.get("finish"):
                    t.Finish = _parse_date(item["finish"])
                if item.get("resource"):
                    t.ResourceNames = item["resource"]
                if item.get("rag"):
                    t.Text1 = item["rag"]
                if item.get("text2"):
                    t.Text2 = item["text2"]
                if item.get("text3"):
                    t.Text3 = item["text3"]
                if item.get("notes"):
                    t.Notes = item["notes"]
                if item.get("manual") is not None:
                    t.Manual = item["manual"]

                created.append({
                    "unique_id": t.UniqueID,
                    "id":        t.ID,
                    "name":      t.Name,
                })
        finally:
            app.CalculateProject()
            app.Calculation = -1

        app.FileSave()
        return json.dumps({
            "created": len(created),
            "tasks":   created,
        }, indent=2)


    @mcp.tool()
    def delete_task(unique_id: int) -> str:
        """Delete a task by its UniqueID. This cannot be undone after save."""
        if is_dry_run():
            return dry_run_response("delete_task", {"unique_id": unique_id})
        app  = get_app()
        proj = get_proj(app)

        for t in proj.Tasks:
            if t is not None and t.UniqueID == unique_id:
                task_name = t.Name
                task_id   = t.ID
                app.SelectRow(task_id, False)
                app.EditDelete()
                app.FileSave()
                return json.dumps({
                    "status":    "deleted",
                    "unique_id": unique_id,
                    "name":      task_name,
                }, indent=2)

        return json.dumps({"error": f"Task UniqueID {unique_id} not found."})


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
        Add a recurring task to the project.

        Args:
            name:            Task name.
            recurrence_type: 'daily', 'weekly', or 'monthly' (default 'weekly').
            start_date:      Recurrence range start (YYYY-MM-DD).
            end_date:        Recurrence range end (YYYY-MM-DD).
            duration_days:   Duration of each occurrence in days (default 1).
            day_of_week:     For weekly: 1=Sun, 2=Mon, ..., 7=Sat (default 2=Monday).
        """
        app  = get_app()
        proj = get_proj(app)
        mpd  = _get_mpd(proj)

        sd = _parse_date(start_date)
        ed = _parse_date(end_date)
        if sd is None or ed is None:
            return json.dumps({"error": "Both start_date and end_date are required (YYYY-MM-DD)."})

        dur = int(duration_days * mpd)

        # pjRecurType: 0=daily, 1=weekly, 2=monthly, 3=yearly
        RECUR_MAP = {"daily": 0, "weekly": 1, "monthly": 2, "yearly": 3}
        rt = RECUR_MAP.get(recurrence_type.lower())
        if rt is None:
            return json.dumps({"error": f"Unknown recurrence_type '{recurrence_type}'. Use: daily, weekly, monthly, yearly."})

        try:
            # MS Project's RecurringTaskInsert is a dialog-only COM method;
            # it cannot be driven programmatically. Instead, we create individual
            # task occurrences under a summary task to simulate recurrence.

            from dateutil.rrule import rrule, DAILY, WEEKLY, MONTHLY, YEARLY
            FREQ_MAP = {"daily": DAILY, "weekly": WEEKLY, "monthly": MONTHLY, "yearly": YEARLY}
            freq = FREQ_MAP.get(recurrence_type.lower(), WEEKLY)

            # Map day_of_week (1=Sun..7=Sat) to dateutil byweekday (0=Mon..6=Sun)
            WEEKDAY_MAP = {1: 6, 2: 0, 3: 1, 4: 2, 5: 3, 6: 4, 7: 5}
            byday = WEEKDAY_MAP.get(day_of_week, 0)

            if freq == WEEKLY:
                dates = list(rrule(freq, dtstart=sd, until=ed, byweekday=byday))
            else:
                dates = list(rrule(freq, dtstart=sd, until=ed))

            if not dates:
                return json.dumps({"error": "No occurrences generated for the given range."})

            # Create summary task
            summary = proj.Tasks.Add(name)
            summary_uid = summary.UniqueID

            # Create each occurrence as a subtask
            occurrence_uids = []
            for i, dt_occ in enumerate(dates, 1):
                occ = proj.Tasks.Add(f"{name} #{i}")
                occ.OutlineIndent()
                occ.Start = dt_occ
                occ.Duration = dur
                occurrence_uids.append(occ.UniqueID)

            app.CalculateProject()
            app.FileSave()

            return json.dumps({
                "status":          "created",
                "name":            name,
                "unique_id":       summary_uid,
                "recurrence_type": recurrence_type,
                "occurrences":     len(dates),
                "start":           start_date,
                "end":             end_date,
            }, indent=2)

        except ImportError:
            return json.dumps({"error": "python-dateutil is required for recurring tasks. Install with: pip install python-dateutil"})
        except Exception as e:
            return json.dumps({"error": f"Failed to create recurring task: {e}"})


    @mcp.tool()
    def copy_task_structure(source_unique_id: int, copies: int = 1) -> str:
        """
        Duplicate a task subtree (reusable programme templates).

        Args:
            source_unique_id: UniqueID of the task to copy (and its children if summary).
            copies:           Number of copies to create (default 1).
        """
        app  = get_app()
        proj = get_proj(app)

        source = _find_task(proj, source_unique_id)
        if source is None:
            return json.dumps({"error": f"Task UniqueID {source_unique_id} not found."})

        # Determine range: source + all children (higher outline level)
        source_id = source.ID
        source_level = source.OutlineLevel
        end_id = source_id

        for t in proj.Tasks:
            if t is None:
                continue
            if t.ID > source_id:
                if t.OutlineLevel > source_level:
                    end_id = t.ID
                else:
                    break

        all_copied = []
        for _copy_num in range(copies):
            # Select the range
            app.SelectRow(source_id, False)
            app.SelectRow(end_id, True)  # extend selection
            app.EditCopy()

            # Paste at end
            last_id = proj.Tasks.Count
            app.SelectRow(last_id, False)
            app.EditPaste()

            # Collect newly created tasks
            new_count = proj.Tasks.Count
            for t in proj.Tasks:
                if t is not None and t.ID > last_id:
                    all_copied.append({
                        "unique_id": t.UniqueID,
                        "name":      t.Name,
                    })

        return json.dumps({
            "status":       "copied",
            "source_name":  source.Name,
            "copied_tasks": all_copied,
        }, indent=2)


    @mcp.tool()
    def indent_task(unique_id: int, direction: str = "indent") -> str:
        """
        Promote or demote a task in the WBS hierarchy.

        Args:
            unique_id: Task UniqueID (required).
            direction: 'indent' to demote (increase level) or 'outdent' to promote (decrease level).
        """
        app  = get_app()
        proj = get_proj(app)

        for t in proj.Tasks:
            if t is not None and t.UniqueID == unique_id:
                old_level = t.OutlineLevel
                app.SelectRow(t.ID, False)
                if direction.lower() == "outdent":
                    app.OutlineOutdent()
                else:
                    app.OutlineIndent()
                app.FileSave()
                return json.dumps({
                    "status":    "updated",
                    "unique_id": unique_id,
                    "name":      t.Name,
                    "old_level": old_level,
                    "new_level": t.OutlineLevel,
                }, indent=2)

        return json.dumps({"error": f"Task UniqueID {unique_id} not found."})


    @mcp.tool()
    def move_task(unique_id: int, after_unique_id: int) -> str:
        """
        Reposition a task to appear after another task.

        Args:
            unique_id:       Task UniqueID to move (required).
            after_unique_id: Place moved task after this task's UniqueID (required).
        """
        app  = get_app()
        proj = get_proj(app)

        t = _find_task(proj, unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})

        after_t = _find_task(proj, after_unique_id)
        if after_t is None:
            return json.dumps({"error": f"Target task UniqueID {after_unique_id} not found."})

        old_id = t.ID
        old_level = t.OutlineLevel

        # Select and cut the source task row
        app.SelectRow(t.ID, False)
        app.EditCut()

        # Re-find the after task (IDs may have shifted after cut)
        after_t = _find_task(proj, after_unique_id)
        if after_t is None:
            # Paste back at original position as fallback
            app.EditPaste()
            return json.dumps({"error": "Target task not found after cut. Task restored."})

        # Select row after the target and paste
        target_row = after_t.ID + 1
        if target_row > proj.Tasks.Count:
            target_row = proj.Tasks.Count
        app.SelectRow(target_row, False)
        app.EditPaste()

        # Re-find moved task and verify
        moved = _find_task(proj, unique_id)
        new_id = moved.ID if moved else None

        return json.dumps({
            "status":    "moved",
            "unique_id": unique_id,
            "name":      moved.Name if moved else "(unknown)",
            "old_id":    old_id,
            "new_id":    new_id,
        }, indent=2)
