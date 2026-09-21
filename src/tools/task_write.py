"""
Field-level task mutations, single and bulk, including the bulk dry-run preview.
"""

import json

from ..com_helpers import get_app, get_proj, _get_mpd, _parse_date, _fmt_date, _find_task


def register_task_write_tools(mcp):
    """Register the task write tools on the FastMCP instance."""

    @mcp.tool()
    def update_task(
        unique_id:        int,
        name:             str = "",
        percent_complete: int = -1,
        notes:            str = "",
        start:            str = "",
        finish:           str = "",
        duration_days:    int = -1,
        manual:           bool = None,
        rag:              str = "",
        text2:            str = "",
        text3:            str = "",
        flag1:            bool = None,
        flag2:            bool = None,
        priority:         int = -1,
        task_type:        str = "",
    ) -> str:
        """
        Update one or more properties of a task identified by UniqueID.
        Only the fields you provide are changed.

        Args:
            unique_id:        Task UniqueID (required).
            name:             New task name.
            percent_complete: 0-100.
            notes:            Free-text notes.
            start:            Start date as YYYY-MM-DD.
            finish:           Finish date as YYYY-MM-DD.
            duration_days:    Duration in working days (0+ to set).
            manual:           True for manually scheduled, False for auto-scheduled.
            rag:              RAG status: 'Red', 'Amber', or 'Green' (stored in Text1).
            text2:            Custom Text2 field.
            text3:            Custom Text3 field.
            flag1:            Custom Flag1 boolean.
            flag2:            Custom Flag2 boolean.
            priority:         Leveling priority 0-1000 (default 500). 0+ to set.
            task_type:        'FixedUnits', 'FixedDuration', or 'FixedWork'.
        """
        app  = get_app()
        proj = get_proj(app)
        mpd  = _get_mpd(proj)

        for t in proj.Tasks:
            if t is None or t.UniqueID != unique_id:
                continue

            changed = []
            if name:
                t.Name = name;              changed.append("name")
            if percent_complete >= 0:
                t.PercentComplete = percent_complete; changed.append("percent_complete")
            if notes:
                t.Notes = notes;            changed.append("notes")
            if start:
                t.Start = _parse_date(start); changed.append("start")
            if finish:
                t.Finish = _parse_date(finish); changed.append("finish")
            if duration_days >= 0:
                t.Duration = duration_days * mpd; changed.append("duration_days")
            if manual is not None:
                t.Manual = manual;          changed.append("manual")
            if rag:
                t.Text1 = rag;              changed.append("rag/text1")
            if text2:
                t.Text2 = text2;            changed.append("text2")
            if text3:
                t.Text3 = text3;            changed.append("text3")
            if flag1 is not None:
                t.Flag1 = flag1;            changed.append("flag1")
            if flag2 is not None:
                t.Flag2 = flag2;            changed.append("flag2")
            if priority >= 0:
                t.Priority = priority;      changed.append("priority")
            if task_type:
                TYPE_MAP = {"fixedunits": 0, "fixedduration": 1, "fixedwork": 2}
                tt = TYPE_MAP.get(task_type.lower())
                if tt is not None:
                    t.Type = tt;            changed.append("type")

            app.FileSave()
            return json.dumps({
                "status":   "updated",
                "unique_id": unique_id,
                "name":     t.Name,
                "changed":  changed,
            }, indent=2)

        return json.dumps({"error": f"Task UniqueID {unique_id} not found."})


    @mcp.tool()
    def bulk_update_rag(updates: str) -> str:
        """
        Update RAG status for multiple tasks at once.

        Args:
            updates: JSON string — list of {unique_id, rag} objects.
                     Example: '[{"unique_id": 42, "rag": "Red"}, {"unique_id": 55, "rag": "Green"}]'
        """
        items = json.loads(updates)
        app   = get_app()
        proj  = get_proj(app)

        uid_map = {t.UniqueID: t for t in proj.Tasks if t is not None}

        results = []
        for item in items:
            uid = item["unique_id"]
            rag = item["rag"]
            if uid in uid_map:
                uid_map[uid].Text1 = rag
                results.append({"unique_id": uid, "status": "updated", "rag": rag})
            else:
                results.append({"unique_id": uid, "status": "not_found"})

        app.FileSave()
        return json.dumps({"updated": len([r for r in results if r["status"] == "updated"]),
                           "results": results}, indent=2)


    @mcp.tool()
    def bulk_update_tasks(updates_json: str) -> str:
        """
        Update multiple tasks in one call. Suspends auto-calc for performance.

        Args:
            updates_json: JSON string — list of objects with fields:
                unique_id (required), name, start, finish, duration_days,
                percent_complete, rag, text2, text3, notes, manual (bool).
                Example: '[{"unique_id": 42, "rag": "Red", "percent_complete": 50}]'
        """
        items = json.loads(updates_json)
        app   = get_app()
        proj  = get_proj(app)
        mpd   = _get_mpd(proj)

        app.Calculation = 0
        try:
            uid_map = {t.UniqueID: t for t in proj.Tasks if t is not None}
            updated = 0
            not_found = []

            for item in items:
                uid = item["unique_id"]
                t = uid_map.get(uid)
                if t is None:
                    not_found.append(uid)
                    continue

                if "name" in item and item["name"]:
                    t.Name = item["name"]
                if "start" in item and item["start"]:
                    t.Start = _parse_date(item["start"])
                if "finish" in item and item["finish"]:
                    t.Finish = _parse_date(item["finish"])
                if "duration_days" in item and item["duration_days"] is not None and item["duration_days"] >= 0:
                    t.Duration = item["duration_days"] * mpd
                if "percent_complete" in item and item["percent_complete"] is not None and item["percent_complete"] >= 0:
                    t.PercentComplete = item["percent_complete"]
                if "rag" in item and item["rag"]:
                    t.Text1 = item["rag"]
                if "text2" in item and item["text2"]:
                    t.Text2 = item["text2"]
                if "text3" in item and item["text3"]:
                    t.Text3 = item["text3"]
                if "notes" in item and item["notes"]:
                    t.Notes = item["notes"]
                if "manual" in item and item["manual"] is not None:
                    t.Manual = item["manual"]

                updated += 1
        finally:
            app.CalculateProject()
            app.Calculation = -1

        app.FileSave()
        return json.dumps({
            "updated":   updated,
            "not_found": not_found,
        }, indent=2)


    @mcp.tool()
    def dry_run_bulk_update(updates_json: str) -> str:
        """
        Preview bulk changes without modifying anything — the enterprise safety net.
        Shows what would change for each task without actually applying updates.

        Args:
            updates_json: JSON string — list of objects with fields:
                unique_id (required), name, start, finish, duration_days,
                percent_complete, rag, text2, text3, notes.
                Same format as bulk_update_tasks.
        """
        items = json.loads(updates_json)
        app   = get_app()
        proj  = get_proj(app)
        mpd   = _get_mpd(proj)

        changes   = []
        not_found = []
        no_change = []

        for item in items:
            uid = item.get("unique_id")
            if uid is None:
                continue

            t = _find_task(proj, uid)
            if t is None:
                not_found.append(uid)
                continue

            field_changes = []

            if "name" in item and item["name"] and item["name"] != t.Name:
                field_changes.append({"field": "name", "old": t.Name, "new": item["name"]})
            if "start" in item and item["start"]:
                old_start = _fmt_date(t.Start)
                if old_start != item["start"]:
                    field_changes.append({"field": "start", "old": old_start, "new": item["start"]})
            if "finish" in item and item["finish"]:
                old_finish = _fmt_date(t.Finish)
                if old_finish != item["finish"]:
                    field_changes.append({"field": "finish", "old": old_finish, "new": item["finish"]})
            if "duration_days" in item and item["duration_days"] is not None:
                old_dur = round(t.Duration / mpd, 2) if t.Duration else 0
                if old_dur != item["duration_days"]:
                    field_changes.append({"field": "duration_days", "old": old_dur, "new": item["duration_days"]})
            if "percent_complete" in item and item["percent_complete"] is not None:
                if t.PercentComplete != item["percent_complete"]:
                    field_changes.append({"field": "percent_complete", "old": t.PercentComplete, "new": item["percent_complete"]})
            if "rag" in item and item["rag"]:
                old_rag = (t.Text1 or "").strip()
                if old_rag != item["rag"]:
                    field_changes.append({"field": "rag", "old": old_rag, "new": item["rag"]})
            if "text2" in item and item["text2"]:
                old = (t.Text2 or "").strip()
                if old != item["text2"]:
                    field_changes.append({"field": "text2", "old": old, "new": item["text2"]})
            if "text3" in item and item["text3"]:
                old = (t.Text3 or "").strip()
                if old != item["text3"]:
                    field_changes.append({"field": "text3", "old": old, "new": item["text3"]})
            if "notes" in item and item["notes"]:
                old = (t.Notes or "").strip()
                if old != item["notes"]:
                    field_changes.append({"field": "notes", "old": old[:50], "new": item["notes"][:50]})

            if field_changes:
                changes.append({
                    "unique_id": uid,
                    "name":      t.Name,
                    "fields":    field_changes,
                })
            else:
                no_change.append(uid)

        total_changes = sum(len(c["fields"]) for c in changes)

        return json.dumps({
            "preview":              True,
            "changes":              changes,
            "not_found":            not_found,
            "no_change":            no_change,
            "total_changes":        total_changes,
            "total_tasks_affected": len(changes),
        }, indent=2)


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
        app.FileSave()

        return json.dumps({
            "status":    "updated",
            "unique_id": unique_id,
            "name":      t.Name,
            "active":    active,
        }, indent=2)


    @mcp.tool()
    def set_task_hyperlink(unique_id: int, url: str, text: str = "", sub_address: str = "") -> str:
        """
        Set a hyperlink on a task.

        Args:
            unique_id:   Task UniqueID.
            url:         The hyperlink URL or file path.
            text:        Display text for the hyperlink (optional).
            sub_address: Sub-address / bookmark within the target (optional).
        """
        app  = get_app()
        proj = get_proj(app)
        t = _find_task(proj, unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})

        t.HyperlinkAddress    = url
        t.HyperlinkScreenTip  = text or url
        if text:
            t.Hyperlink = text
        if sub_address:
            t.HyperlinkSubAddress = sub_address

        app.FileSave()
        return json.dumps({
            "status":    "updated",
            "unique_id": unique_id,
            "name":      t.Name,
            "hyperlink": url,
            "text":      text or url,
        }, indent=2)
