"""
Task scheduling controls: task mode, constraints, deadlines, and estimated flags.
"""

import json

from ..com_helpers import get_app, get_proj, _parse_date, _fmt_date, _find_task


def register_scheduling_tools(mcp):
    """Register the scheduling tools on the FastMCP instance."""

    @mcp.tool()
    def set_task_mode(unique_id: int, manual: bool = True) -> str:
        """
        Set a task to manually or automatically scheduled.

        Args:
            unique_id: Task UniqueID (required).
            manual:    True for manually scheduled (default), False for auto-scheduled.
        """
        app  = get_app()
        proj = get_proj(app)

        for t in proj.Tasks:
            if t is not None and t.UniqueID == unique_id:
                t.Manual = manual
                app.FileSave()
                return json.dumps({
                    "status":    "updated",
                    "unique_id": unique_id,
                    "name":      t.Name,
                    "manual":    manual,
                }, indent=2)

        return json.dumps({"error": f"Task UniqueID {unique_id} not found."})


    @mcp.tool()
    def bulk_set_task_mode(updates_json: str) -> str:
        """
        Set manual/auto schedule mode for multiple tasks, or by scope.

        Args:
            updates_json: JSON string — EITHER:
                A list of {unique_id, manual} objects:
                  '[{"unique_id": 42, "manual": true}]'
                OR a scope object:
                  '{"mode": "manual", "scope": "all"}'
                  '{"mode": "auto", "scope": "summary"}'
                  '{"mode": "manual", "scope": "non_summary"}'
        """
        data = json.loads(updates_json)
        app  = get_app()
        proj = get_proj(app)

        updated = 0

        if isinstance(data, dict) and "scope" in data:
            manual = data.get("mode", "manual").lower() == "manual"
            scope  = data.get("scope", "all").lower()

            for t in proj.Tasks:
                if t is None:
                    continue
                if scope == "all":
                    t.Manual = manual; updated += 1
                elif scope == "summary" and t.Summary:
                    t.Manual = manual; updated += 1
                elif scope == "non_summary" and not t.Summary:
                    t.Manual = manual; updated += 1

        else:
            items = data if isinstance(data, list) else [data]
            uid_map = {t.UniqueID: t for t in proj.Tasks if t is not None}
            for item in items:
                uid = item["unique_id"]
                t = uid_map.get(uid)
                if t is not None:
                    t.Manual = item.get("manual", True)
                    updated += 1

        app.FileSave()
        return json.dumps({"updated": updated}, indent=2)


    @mcp.tool()
    def set_constraint(unique_id: int, constraint_type: str = "SNET", constraint_date: str = "") -> str:
        """
        Set a scheduling constraint on a task.

        Args:
            unique_id:       Task UniqueID (required).
            constraint_type: One of: ASAP, ALAP, MSO, MFO, SNET, SNLT, FNET, FNLT (default SNET).
            constraint_date: Date as YYYY-MM-DD (required for all types except ASAP/ALAP).
        """
        CONSTRAINT_MAP = {
            "ASAP": 0, "ALAP": 1, "MSO": 2, "MFO": 3,
            "SNET": 4, "SNLT": 5, "FNET": 6, "FNLT": 7,
        }

        ct = constraint_type.upper()
        if ct not in CONSTRAINT_MAP:
            return json.dumps({"error": f"Unknown constraint type '{constraint_type}'. Use: {list(CONSTRAINT_MAP.keys())}"})

        app  = get_app()
        proj = get_proj(app)

        for t in proj.Tasks:
            if t is not None and t.UniqueID == unique_id:
                t.ConstraintType = CONSTRAINT_MAP[ct]
                if constraint_date and ct not in ("ASAP", "ALAP"):
                    t.ConstraintDate = _parse_date(constraint_date)
                app.FileSave()
                return json.dumps({
                    "status":          "updated",
                    "unique_id":       unique_id,
                    "name":            t.Name,
                    "constraint_type": ct,
                    "constraint_date": constraint_date or "N/A",
                }, indent=2)

        return json.dumps({"error": f"Task UniqueID {unique_id} not found."})


    @mcp.tool()
    def clear_estimated_flags() -> str:
        """
        Remove the estimated '?' flag from all task dates in the active project.
        This cleans up the question marks that appear on dates in MS Project.
        """
        app  = get_app()
        proj = get_proj(app)

        count = 0
        for t in proj.Tasks:
            if t is not None:
                try:
                    t.Estimated = False
                    count += 1
                except Exception:
                    pass

        app.FileSave()
        return json.dumps({"status": "cleared", "tasks_updated": count}, indent=2)


    @mcp.tool()
    def set_deadline(unique_id: int, deadline_date: str) -> str:
        """
        Set a soft deadline on a task. Shows a visual indicator if finish > deadline.
        Unlike hard constraints, deadlines don't affect scheduling.

        Args:
            unique_id:     Task UniqueID (required).
            deadline_date: Deadline as YYYY-MM-DD, or 'clear' to remove.
        """
        app  = get_app()
        proj = get_proj(app)

        t = _find_task(proj, unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})

        if deadline_date.lower() == "clear":
            t.Deadline = "NA"
            app.FileSave()
            return json.dumps({
                "status":    "cleared",
                "unique_id": unique_id,
                "name":      t.Name,
                "deadline":  None,
            }, indent=2)

        dl = _parse_date(deadline_date)
        t.Deadline = dl
        app.FileSave()

        deadline_missed = False
        try:
            if t.Finish and t.Finish > dl:
                deadline_missed = True
        except Exception:
            pass

        return json.dumps({
            "status":          "set",
            "unique_id":       unique_id,
            "name":            t.Name,
            "deadline":        deadline_date,
            "finish":          _fmt_date(t.Finish),
            "deadline_missed": deadline_missed,
        }, indent=2)


    @mcp.tool()
    def bulk_set_deadlines(deadlines_json: str) -> str:
        """
        Set deadlines on multiple tasks at once.

        Args:
            deadlines_json: JSON string — list of {unique_id, deadline_date}.
                deadline_date can be 'clear' to remove the deadline.
                Example: '[{"unique_id": 42, "deadline_date": "2026-06-01"},
                           {"unique_id": 55, "deadline_date": "clear"}]'
        """
        items = json.loads(deadlines_json)
        app   = get_app()
        proj  = get_proj(app)

        set_count = 0
        cleared = 0
        not_found = []
        errors = []

        for item in items:
            uid = item["unique_id"]
            dd  = item["deadline_date"]

            t = _find_task(proj, uid)
            if t is None:
                not_found.append(uid)
                continue

            try:
                if dd.lower() == "clear":
                    t.Deadline = "NA"
                    cleared += 1
                else:
                    t.Deadline = _parse_date(dd)
                    set_count += 1
            except Exception as e:
                errors.append({"unique_id": uid, "error": str(e)})

        return json.dumps({
            "set":       set_count,
            "cleared":   cleared,
            "not_found": not_found,
            "errors":    errors,
        }, indent=2)


    @mcp.tool()
    def get_constraints() -> str:
        """Return all tasks with non-default (non-ASAP) scheduling constraints."""
        CONSTRAINT_NAMES = {
            0: "ASAP", 1: "ALAP", 2: "MSO", 3: "MFO",
            4: "SNET", 5: "SNLT", 6: "FNET", 7: "FNLT",
        }
        app  = get_app()
        proj = get_proj(app)

        results = []
        for t in proj.Tasks:
            if t is None or t.Summary:
                continue
            try:
                ct = t.ConstraintType
                if ct != 0:  # 0 = ASAP (default)
                    results.append({
                        "unique_id":       t.UniqueID,
                        "name":            t.Name,
                        "constraint_type": CONSTRAINT_NAMES.get(ct, f"Unknown({ct})"),
                        "constraint_date": _fmt_date(t.ConstraintDate),
                    })
            except Exception:
                continue

        return json.dumps({"count": len(results), "tasks": results}, indent=2)
