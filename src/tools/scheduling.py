"""
Task scheduling controls: task mode, constraints, deadlines, and estimated flags.
"""

import json

from ..com_helpers import get_app, get_proj, _fmt_date, _find_task, _to_naive
from ..com_write import to_com_date, commit

CONSTRAINT_MAP = {"ASAP": 0, "ALAP": 1, "MSO": 2, "MFO": 3, "SNET": 4, "SNLT": 5, "FNET": 6, "FNLT": 7}
FINISH_CONSTRAINTS = ("MFO", "FNET", "FNLT")


def _deadline_value(proj, deadline_date):
    """'' or 'clear' -> 'NA' (clears the deadline); otherwise end of that working day. Raises ValueError."""
    if not deadline_date or deadline_date.strip().lower() == "clear":
        return "NA"
    return to_com_date(proj, deadline_date, end_of_day=True, field="deadline_date")


def _parse_list(text, what):
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError(f"{what} must be a JSON array of objects.")
    for i, item in enumerate(data):
        if not isinstance(item, dict) or "unique_id" not in item:
            raise ValueError(f"item[{i}] must be an object with a unique_id.")
    return data


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
        t = _find_task(proj, unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})
        t.Manual = manual
        commit(app, proj)
        return json.dumps({"status": "updated", "unique_id": unique_id, "name": t.Name, "manual": bool(t.Manual)}, indent=2)

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
        updated, not_found = 0, []

        if isinstance(data, dict):
            mode = str(data.get("mode", "manual")).lower()
            scope = str(data.get("scope", "all")).lower()
            if mode not in ("manual", "auto") or scope not in ("all", "summary", "non_summary"):
                raise ValueError("Scope form needs mode 'manual'|'auto' and scope 'all'|'summary'|'non_summary'.")
            for t in proj.Tasks:
                if t is None or (scope == "summary" and not t.Summary) or (scope == "non_summary" and t.Summary):
                    continue
                t.Manual = mode == "manual"
                updated += 1
        else:
            uid_map = {t.UniqueID: t for t in proj.Tasks if t is not None}
            for item in _parse_list(updates_json, "updates_json"):
                t = uid_map.get(item["unique_id"])
                if t is None:
                    not_found.append(item["unique_id"])
                    continue
                t.Manual = bool(item.get("manual", True))
                updated += 1

        commit(app, proj)
        return json.dumps({"updated": updated, "not_found": not_found}, indent=2)

    @mcp.tool()
    def set_constraint(unique_id: int, constraint_type: str = "SNET", constraint_date: str = "") -> str:
        """
        Set a scheduling constraint on a task. Validated before anything is written.

        Args:
            unique_id:       Task UniqueID (required).
            constraint_type: One of: ASAP, ALAP, MSO, MFO, SNET, SNLT, FNET, FNLT (default SNET).
            constraint_date: Date as YYYY-MM-DD (required for all types except ASAP/ALAP).
                             Start-type constraints use the default start time, finish-type
                             constraints (MFO, FNET, FNLT) the end of that working day.
        """
        ct = constraint_type.upper().strip()
        if ct not in CONSTRAINT_MAP:
            return json.dumps({"error": f"Unknown constraint type '{constraint_type}'. Use: {list(CONSTRAINT_MAP)}"})
        needs_date = ct not in ("ASAP", "ALAP")
        if needs_date and not constraint_date:
            return json.dumps({"error": f"{ct} requires constraint_date (YYYY-MM-DD)."})
        app  = get_app()
        proj = get_proj(app)
        t = _find_task(proj, unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})
        date = to_com_date(proj, constraint_date, end_of_day=ct in FINISH_CONSTRAINTS,
                           field="constraint_date") if needs_date else None

        t.ConstraintType = CONSTRAINT_MAP[ct]
        if date is not None:
            t.ConstraintDate = date
        commit(app, proj)
        result = {"status": "updated", "unique_id": unique_id, "name": t.Name, "constraint_type": ct,
                  "constraint_date": _fmt_date(t.ConstraintDate) if needs_date else None}
        if t.Manual:
            result["warning"] = "Task is manually scheduled: MS Project ignores constraints until it is auto-scheduled."
        return json.dumps(result, indent=2)

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
            if t is not None and t.Estimated:
                t.Estimated = False
                count += 1
        commit(app, proj)
        return json.dumps({"status": "cleared", "tasks_updated": count}, indent=2)

    @mcp.tool()
    def set_deadline(unique_id: int, deadline_date: str) -> str:
        """
        Set a soft deadline on a task. Shows a visual indicator if finish > deadline.
        Unlike hard constraints, deadlines don't affect scheduling.

        Args:
            unique_id:     Task UniqueID (required).
            deadline_date: Deadline as YYYY-MM-DD (end of that working day), or '' / 'clear' to remove.
        """
        app  = get_app()
        proj = get_proj(app)
        t = _find_task(proj, unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})
        value = _deadline_value(proj, deadline_date)
        t.Deadline = value
        commit(app, proj)
        if value == "NA":
            return json.dumps({"status": "cleared", "unique_id": unique_id, "name": t.Name, "deadline": None}, indent=2)
        missed = bool(t.Finish) and _to_naive(t.Finish) > value.replace(tzinfo=None)
        return json.dumps({"status": "set", "unique_id": unique_id, "name": t.Name, "deadline": _fmt_date(t.Deadline),
                           "finish": _fmt_date(t.Finish), "deadline_missed": missed}, indent=2)

    @mcp.tool()
    def bulk_set_deadlines(deadlines_json: str) -> str:
        """
        Set deadlines on multiple tasks at once. All dates are validated before any write.

        Args:
            deadlines_json: JSON string — list of {unique_id, deadline_date}.
                deadline_date can be 'clear' (or '') to remove the deadline.
                Example: '[{"unique_id": 42, "deadline_date": "2026-06-01"},
                           {"unique_id": 55, "deadline_date": "clear"}]'
        """
        app  = get_app()
        proj = get_proj(app)
        planned, not_found = [], []
        for i, item in enumerate(_parse_list(deadlines_json, "deadlines_json")):
            try:
                value = _deadline_value(proj, item.get("deadline_date", ""))
            except ValueError as e:
                raise ValueError(f"item[{i}] (unique_id {item['unique_id']}): {e}") from e
            t = _find_task(proj, item["unique_id"])
            if t is None:
                not_found.append(item["unique_id"])
            else:
                planned.append((t, value))
        for t, value in planned:
            t.Deadline = value
        commit(app, proj)
        return json.dumps({"set": sum(v != "NA" for _, v in planned), "cleared": sum(v == "NA" for _, v in planned),
                           "not_found": not_found}, indent=2)


    @mcp.tool()
    def get_constraints() -> str:
        """Return all tasks with non-default (non-ASAP) scheduling constraints."""
        CONSTRAINT_NAMES = {v: k for k, v in CONSTRAINT_MAP.items()}
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
