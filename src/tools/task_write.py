"""
Field-level task mutations, single and bulk, including the bulk dry-run preview.

All three share the validation and writing layer in src/task_fields.py.
"""

import json
from typing import Optional
from urllib.parse import urlparse

from ..com_helpers import get_app, get_proj, _get_mpd, _fmt_date, _find_task
from ..com_write import commit, batch_calc, validate_rag
from ..task_fields import FIELD_ATTR, SAFE_URL_SCHEMES, validate_changes, apply_changes

def _parse_updates(updates_json):
    items = json.loads(updates_json)
    if not isinstance(items, list):
        raise ValueError("updates_json must be a JSON array of objects.")
    for i, item in enumerate(items):
        if not isinstance(item, dict) or "unique_id" not in item:
            raise ValueError(f"item[{i}] must be an object with a unique_id.")
    return items


def register_task_write_tools(mcp):
    """Register the task write tools on the FastMCP instance."""

    @mcp.tool()
    def update_task(
        unique_id:        int,
        name:             Optional[str] = None,
        percent_complete: Optional[int] = None,
        notes:            Optional[str] = None,
        start:            Optional[str] = None,
        finish:           Optional[str] = None,
        duration_days:    Optional[float] = None,
        manual:           Optional[bool] = None,
        rag:              Optional[str] = None,
        text2:            Optional[str] = None,
        text3:            Optional[str] = None,
        flag1:            Optional[bool] = None,
        flag2:            Optional[bool] = None,
        priority:         Optional[int] = None,
        task_type:        Optional[str] = None,
    ) -> str:
        """
        Update one or more properties of a task identified by UniqueID.
        Only the fields you provide are changed; pass "" to clear notes, rag, text2 or text3.
        Everything is validated before any field is written.

        Args:
            unique_id:        Task UniqueID (required).
            name:             New task name (non-empty).
            percent_complete: 0-100.
            notes:            Free-text notes ("" clears).
            start:            Start date YYYY-MM-DD (project default start time).
            finish:           Finish date YYYY-MM-DD (end of that working day).
            duration_days:    Duration in working days, 0 or more.
            manual:           True for manually scheduled, False for auto-scheduled.
            rag:              RAG status in Text1: 'Red', 'Amber', 'Green' ("" clears).
            text2:            Custom Text2 field ("" clears).
            text3:            Custom Text3 field ("" clears).
            flag1:            Custom Flag1 boolean.
            flag2:            Custom Flag2 boolean.
            priority:         Leveling priority 0-1000.
            task_type:        'FixedUnits', 'FixedDuration', or 'FixedWork'.
        """
        app  = get_app()
        proj = get_proj(app)
        t = _find_task(proj, unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})
        values = validate_changes(proj, {
            "name": name, "percent_complete": percent_complete, "notes": notes, "start": start,
            "finish": finish, "duration_days": duration_days, "manual": manual, "rag": rag,
            "text2": text2, "text3": text3, "flag1": flag1, "flag2": flag2, "priority": priority,
            "task_type": task_type,
        })
        if not values:
            return json.dumps({"error": "No fields to update were provided."})
        changed, warnings = apply_changes(proj, t, values)
        commit(app, proj)
        result = {"status": "updated", "unique_id": unique_id, "name": t.Name, "changed": changed}
        if warnings:
            result["warnings"] = warnings
        return json.dumps(result, indent=2)

    @mcp.tool()
    def bulk_update_rag(updates: str) -> str:
        """
        Update RAG status for multiple tasks at once. Every RAG value is validated first.

        Args:
            updates: JSON string — list of {unique_id, rag} objects (rag: Red, Amber, Green).
                     Example: '[{"unique_id": 42, "rag": "Red"}, {"unique_id": 55, "rag": "Green"}]'
        """
        items = _parse_updates(updates)
        for i, item in enumerate(items):
            try:
                item["rag"] = validate_rag(item.get("rag"))
            except ValueError as e:
                raise ValueError(f"item[{i}]: {e}") from e
        app  = get_app()
        proj = get_proj(app)
        uid_map = {t.UniqueID: t for t in proj.Tasks if t is not None}
        results = []
        for item in items:
            t = uid_map.get(item["unique_id"])
            if t is None:
                results.append({"unique_id": item["unique_id"], "status": "not_found"})
                continue
            t.Text1 = item["rag"]
            results.append({"unique_id": item["unique_id"], "status": "updated", "rag": item["rag"]})
        commit(app, proj)
        return json.dumps({"updated": sum(r["status"] == "updated" for r in results), "results": results}, indent=2)

    @mcp.tool()
    def bulk_update_tasks(updates_json: str) -> str:
        """
        Update multiple tasks in one call. Suspends auto-calc for performance.
        All items are validated before any task is written; unknown fields are rejected.

        Args:
            updates_json: JSON string — list of objects with fields:
                unique_id (required), name, start, finish, duration_days,
                percent_complete, rag, text2, text3, notes, manual, flag1, flag2,
                priority, task_type.
                Example: '[{"unique_id": 42, "rag": "Red", "percent_complete": 50}]'
        """
        items = _parse_updates(updates_json)
        app  = get_app()
        proj = get_proj(app)
        uid_map = {t.UniqueID: t for t in proj.Tasks if t is not None}
        planned, not_found = [], []
        for i, item in enumerate(items):
            fields = {k: v for k, v in item.items() if k != "unique_id"}
            try:
                values = validate_changes(proj, fields)
            except ValueError as e:
                raise ValueError(f"item[{i}] (unique_id {item['unique_id']}): {e}") from e
            if item["unique_id"] not in uid_map:
                not_found.append(item["unique_id"])
            elif values:
                planned.append((uid_map[item["unique_id"]], values))
        results = []
        with batch_calc(app):
            for t, values in planned:
                changed, warnings = apply_changes(proj, t, values)
                results.append({"unique_id": t.UniqueID, "changed": changed, **({"warnings": warnings} if warnings else {})})
        commit(app, proj)
        return json.dumps({"updated": len(results), "not_found": not_found, "results": results}, indent=2)

    @mcp.tool()
    def dry_run_bulk_update(updates_json: str) -> str:
        """
        Preview bulk changes without modifying anything — the enterprise safety net.
        Uses the same validation as bulk_update_tasks, so an invalid item is reported here too.

        Args:
            updates_json: JSON string — same format as bulk_update_tasks.
        """
        items = _parse_updates(updates_json)
        app  = get_app()
        proj = get_proj(app)
        mpd  = _get_mpd(proj)
        changes, not_found, no_change, invalid = [], [], [], []
        for item in items:
            uid = item["unique_id"]
            t = _find_task(proj, uid)
            if t is None:
                not_found.append(uid)
                continue
            try:
                values = validate_changes(proj, {k: v for k, v in item.items() if k != "unique_id"})
            except ValueError as e:
                invalid.append({"unique_id": uid, "error": str(e)})
                continue
            field_changes = []
            for key, new in values.items():
                if key == "duration_days":
                    old = round(t.Duration / mpd, 2) if t.Duration else 0
                elif key in ("start", "finish"):
                    old, new = _fmt_date(getattr(t, FIELD_ATTR[key])), new.strftime("%Y-%m-%d")
                else:
                    old = getattr(t, FIELD_ATTR[key])
                if old != new:
                    field_changes.append({"field": key, "old": old, "new": new})
            if field_changes:
                changes.append({"unique_id": uid, "name": t.Name, "fields": field_changes})
            else:
                no_change.append(uid)
        return json.dumps({
            "preview": True, "changes": changes, "not_found": not_found, "no_change": no_change,
            "invalid": invalid, "total_changes": sum(len(c["fields"]) for c in changes),
            "total_tasks_affected": len(changes),
        }, indent=2, default=str)

    @mcp.tool()
    def set_task_active(unique_id: int, active: bool = True) -> str:
        """
        Activate or deactivate a task. Deactivated tasks are excluded from scheduling
        but remain visible (soft-delete).

        Args:
            unique_id: Task UniqueID (required).
            active:    True to activate (default), False to deactivate.
        """
        app  = get_app()
        proj = get_proj(app)
        t = _find_task(proj, unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})
        t.Active = active
        commit(app, proj)
        return json.dumps({"status": "updated", "unique_id": unique_id, "name": t.Name, "active": bool(t.Active)}, indent=2)

    @mcp.tool()
    def set_task_hyperlink(unique_id: int, url: str, text: str = "", sub_address: str = "") -> str:
        """
        Set a hyperlink on a task.

        Args:
            unique_id:   Task UniqueID.
            url:         http(s), mailto, ftp or file URL, or a file path. Script schemes are refused.
            text:        Display text for the hyperlink (optional).
            sub_address: Sub-address / bookmark within the target (optional).
        """
        scheme = urlparse(url.strip()).scheme.lower()
        if not url.strip() or (scheme not in SAFE_URL_SCHEMES and len(scheme) > 1):
            return json.dumps({"error": f"Refusing hyperlink scheme '{scheme}:'. Use http(s), mailto, ftp, file or a path."})
        app  = get_app()
        proj = get_proj(app)
        t = _find_task(proj, unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})
        t.HyperlinkAddress   = url
        t.HyperlinkScreenTip = text or url
        if text:
            t.Hyperlink = text
        if sub_address:
            t.HyperlinkSubAddress = sub_address
        commit(app, proj)
        return json.dumps({"status": "updated", "unique_id": unique_id, "name": t.Name,
                           "hyperlink": url, "text": text or url}, indent=2)
