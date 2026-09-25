"""
Task creation, deletion and outline level. Moving, copying and recurrence live in task_placement.

Every tool here works on COM Task objects directly (never on view rows), so a filtered,
sorted or collapsed view cannot redirect an operation to a different task.
"""

import json

from ..com_helpers import get_app, get_proj, _get_mpd, _find_task
from ..com_write import to_com_date, commit, batch_calc, find_resource, validate_rag


def _task_spec(proj, item):
    """Validate one task definition before anything is created. Raises ValueError."""
    name = str(item.get("name") or "").strip()
    if not name:
        raise ValueError("Task name is required.")
    level = int(item.get("outline_level", 1))
    if level < 1:
        raise ValueError("outline_level must be 1 or more.")
    duration = float(item.get("duration_days", 1))
    if duration < 0:
        raise ValueError("duration_days cannot be negative.")
    start = to_com_date(proj, item["start"], field="start") if item.get("start") else None
    finish = to_com_date(proj, item["finish"], end_of_day=True, field="finish") if item.get("finish") else None
    if start and finish and finish < start:
        raise ValueError(f"finish {item['finish']} is before start {item['start']}.")
    resource = item.get("resource") or ""
    if resource and find_resource(proj, resource) is None:
        raise ValueError(f"Resource '{resource}' not found. Create it with add_resource first.")
    before = None
    after_uid = int(item.get("after_unique_id") or 0)
    if after_uid:
        after = _find_task(proj, after_uid)
        if after is None:
            raise ValueError(f"after_unique_id {after_uid} not found.")
        before = after.ID + 1 if after.ID < proj.Tasks.Count else None
    return {
        "name": name, "level": level, "duration": duration, "milestone": bool(item.get("milestone")),
        "start": start, "finish": finish, "resource": resource, "before": before,
        "rag": validate_rag(item["rag"]) if item.get("rag") else "",
        "notes": item.get("notes") or "", "text2": item.get("text2") or "", "text3": item.get("text3") or "",
        "manual": item.get("manual"),
    }


def _create_task(proj, spec):
    """Create a task from a validated spec. The task is deleted again if any write fails."""
    task = proj.Tasks.Add(spec["name"], spec["before"]) if spec["before"] else proj.Tasks.Add(spec["name"])
    try:
        task.OutlineLevel = spec["level"]
        if spec["manual"] is not None:
            task.Manual = bool(spec["manual"])
        if spec["milestone"]:
            task.Duration = 0
            task.Milestone = True
        else:
            task.Duration = round(spec["duration"] * _get_mpd(proj))
        if spec["start"]:
            task.Start = spec["start"]
        if spec["finish"]:
            task.Finish = spec["finish"]
        for field in ("notes", "text2", "text3"):
            if spec[field]:
                setattr(task, field.capitalize(), spec[field])
        if spec["rag"]:
            task.Text1 = spec["rag"]
        if spec["resource"]:
            task.Assignments.Add(task.ID, find_resource(proj, spec["resource"]).ID, 1.0)
    except Exception:
        task.Delete()
        raise
    return task


def _task_ref(task):
    return {"unique_id": task.UniqueID, "id": task.ID, "name": task.Name}


def register_task_structure_tools(mcp):
    """Register the task structure tools on the FastMCP instance."""

    @mcp.tool()
    def add_task(
        name:          str,
        outline_level: int   = 1,
        start:         str   = "",
        finish:        str   = "",
        duration_days: float = 1,
        milestone:     bool  = False,
        notes:         str   = "",
        resource:      str   = "",
        rag:           str   = "",
        after_unique_id: int = 0,
    ) -> str:
        """
        Add a new task to the active project. All inputs are validated before the task is created.

        Args:
            name:            Task name (required, non-empty).
            outline_level:   WBS level (1 = top-level, 2 = sub-task, etc.).
            start:           Start date YYYY-MM-DD (optional; the project's default start time is used).
            finish:          Finish date YYYY-MM-DD (optional; end of that working day). Must not precede start.
            duration_days:   Duration in working days, 0 or more (default 1).
            milestone:       True to create as a milestone.
            notes:           Free-text notes.
            resource:        Name of an existing resource to assign (not created implicitly).
            rag:             RAG status stored in Text1: Red, Amber, or Green.
            after_unique_id: Insert directly after this task's UniqueID (0 = append at end).
        """
        app  = get_app()
        proj = get_proj(app)
        spec = _task_spec(proj, {
            "name": name, "outline_level": outline_level, "start": start, "finish": finish,
            "duration_days": duration_days, "milestone": milestone, "notes": notes,
            "resource": resource, "rag": rag, "after_unique_id": after_unique_id,
        })
        with batch_calc(app):
            task = _create_task(proj, spec)
        commit(app, proj)
        return json.dumps({"status": "created", **_task_ref(task)}, indent=2)

    @mcp.tool()
    def bulk_add_tasks(tasks_json: str) -> str:
        """
        Add multiple tasks in one call. Critical for roadmap generation.
        Every item is validated first; nothing is created if any item is invalid.
        Suspends auto-calc for performance. outline_level controls WBS hierarchy.

        Args:
            tasks_json: JSON string — list of task objects with fields:
                name (required), outline_level (default 1), start, finish,
                duration_days (default 1), milestone (bool), resource (existing),
                rag (Red/Amber/Green), text2, text3, notes, manual (bool), after_unique_id.
                Example: '[{"name": "Phase 1", "outline_level": 1},
                           {"name": "Task A", "outline_level": 2, "start": "2026-04-01"}]'
        """
        items = json.loads(tasks_json)
        if not isinstance(items, list) or not items:
            raise ValueError("tasks_json must be a non-empty JSON array of task objects.")
        app  = get_app()
        proj = get_proj(app)
        specs = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"item[{i}] must be an object.")
            try:
                specs.append(_task_spec(proj, item))
            except ValueError as e:
                raise ValueError(f"item[{i}]: {e}") from e
        with batch_calc(app):
            created = [_task_ref(_create_task(proj, spec)) for spec in specs]
        commit(app, proj)
        return json.dumps({"created": len(created), "tasks": created}, indent=2)

    @mcp.tool()
    def delete_task(unique_id: int) -> str:
        """Delete a task (and its subtasks, if it is a summary) by its UniqueID."""
        app  = get_app()
        proj = get_proj(app)
        t = _find_task(proj, unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})
        name = t.Name
        t.Delete()
        commit(app, proj)
        return json.dumps({"status": "deleted", "unique_id": unique_id, "name": name}, indent=2)

    @mcp.tool()
    def indent_task(unique_id: int, direction: str = "indent") -> str:
        """
        Promote or demote a task in the WBS hierarchy.

        Args:
            unique_id: Task UniqueID (required).
            direction: 'indent' to demote (increase level) or 'outdent' to promote (decrease level).
        """
        direction = direction.lower().strip()
        if direction not in ("indent", "outdent"):
            return json.dumps({"error": f"Invalid direction '{direction}'. Use 'indent' or 'outdent'."})
        app  = get_app()
        proj = get_proj(app)
        t = _find_task(proj, unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})
        old_level = t.OutlineLevel
        if direction == "outdent":
            t.OutlineOutdent()
        else:
            t.OutlineIndent()
        if t.OutlineLevel == old_level:
            return json.dumps({"error": f"Cannot {direction} '{t.Name}' (level {old_level}): "
                                        "no valid parent/level for that move."})
        commit(app, proj)
        return json.dumps({"status": "updated", "unique_id": unique_id, "name": t.Name,
                           "old_level": old_level, "new_level": t.OutlineLevel}, indent=2)
