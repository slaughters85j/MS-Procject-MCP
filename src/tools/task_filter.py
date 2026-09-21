"""
Structured task filtering, grouping, named view filters, and CSV export of filtered tasks.
"""

import json

from ..com_helpers import get_app, get_proj, _parse_date, task_to_dict
from ..guards import (
    validate_safe_path, is_dry_run, dry_run_response, prepare_task_response, _RESPONSE_MGMT,
)


def register_task_filter_tools(mcp):
    """Register the task filter tools on the FastMCP instance."""

    @mcp.tool()
    def filter_tasks(filters_json: str) -> str:
        """
        Powerful AND-logic filtering across all task fields with sort and pagination.

        Args:
            filters_json: JSON string with filter keys (all optional):
                rag, resource, start_after, start_before, finish_after, finish_before,
                min_pct, max_pct, outline_level, critical (bool), milestone (bool),
                active (bool), summary (bool), name_contains,
                text1, text2, text3, flag1 (bool), flag2 (bool),
                sort_by (field name), sort_desc (bool), limit (int), offset (int).
                Example: '{"rag": "Red", "critical": true, "limit": 20}'
        """
        f = json.loads(filters_json)
        app  = get_app()
        proj = get_proj(app)

        predicates = []

        if "rag" in f:
            v = f["rag"].lower()
            predicates.append(lambda t, _v=v: (t.Text1 or "").strip().lower() == _v)
        if "resource" in f:
            v = f["resource"].lower()
            predicates.append(lambda t, _v=v: _v in (t.ResourceNames or "").lower())
        if "start_after" in f:
            d = _parse_date(f["start_after"])
            predicates.append(lambda t, _d=d: t.Start is not None and t.Start >= _d)
        if "start_before" in f:
            d = _parse_date(f["start_before"])
            predicates.append(lambda t, _d=d: t.Start is not None and t.Start <= _d)
        if "finish_after" in f:
            d = _parse_date(f["finish_after"])
            predicates.append(lambda t, _d=d: t.Finish is not None and t.Finish >= _d)
        if "finish_before" in f:
            d = _parse_date(f["finish_before"])
            predicates.append(lambda t, _d=d: t.Finish is not None and t.Finish <= _d)
        if "min_pct" in f:
            v = f["min_pct"]
            predicates.append(lambda t, _v=v: t.PercentComplete >= _v)
        if "max_pct" in f:
            v = f["max_pct"]
            predicates.append(lambda t, _v=v: t.PercentComplete <= _v)
        if "outline_level" in f:
            v = f["outline_level"]
            predicates.append(lambda t, _v=v: t.OutlineLevel == _v)
        if "critical" in f:
            v = f["critical"]
            predicates.append(lambda t, _v=v: bool(t.Critical) == _v)
        if "milestone" in f:
            v = f["milestone"]
            predicates.append(lambda t, _v=v: bool(t.Milestone) == _v)
        if "active" in f:
            v = f["active"]
            predicates.append(lambda t, _v=v: bool(t.Active) == _v)
        if "summary" in f:
            v = f["summary"]
            predicates.append(lambda t, _v=v: bool(t.Summary) == _v)
        if "name_contains" in f:
            v = f["name_contains"].lower()
            predicates.append(lambda t, _v=v: _v in t.Name.lower())
        if "text1" in f:
            v = f["text1"].lower()
            predicates.append(lambda t, _v=v: (t.Text1 or "").strip().lower() == _v)
        if "text2" in f:
            v = f["text2"].lower()
            predicates.append(lambda t, _v=v: (t.Text2 or "").strip().lower() == _v)
        if "text3" in f:
            v = f["text3"].lower()
            predicates.append(lambda t, _v=v: (t.Text3 or "").strip().lower() == _v)
        if "flag1" in f:
            v = f["flag1"]
            predicates.append(lambda t, _v=v: bool(t.Flag1) == _v)
        if "flag2" in f:
            v = f["flag2"]
            predicates.append(lambda t, _v=v: bool(t.Flag2) == _v)

        # Collect matching tasks
        matched = []
        for t in proj.Tasks:
            if t is None:
                continue
            if all(p(t) for p in predicates):
                matched.append(task_to_dict(t, proj))

        # Sort
        sort_by = f.get("sort_by", "")
        if sort_by and matched:
            desc = f.get("sort_desc", False)
            try:
                matched.sort(key=lambda x: x.get(sort_by) or "", reverse=desc)
            except Exception:
                pass

        total = len(matched)
        offset = f.get("offset", 0)
        limit  = f.get("limit", 0)

        if _RESPONSE_MGMT:
            # Use response module for pagination + stripping + formatting.
            # limit=0 in filter_tasks means "all" — translate to -1 for paginate().
            effective_limit = limit if limit > 0 else -1
            return prepare_task_response(
                matched, offset=offset, limit=effective_limit,
            )

        # Fallback: legacy behavior
        if offset > 0:
            matched = matched[offset:]
        if limit > 0:
            matched = matched[:limit]

        return json.dumps({
            "total_matching": total,
            "returned":       len(matched),
            "offset":         offset,
            "limit":          limit or total,
            "tasks":          matched,
        }, indent=2)


    @mcp.tool()
    def group_tasks_by(field: str, include_tasks: bool = False) -> str:
        """
        Group non-summary tasks by a field and return counts per group.

        Args:
            field:         Field to group by: 'rag', 'resource', 'outline_level', 'critical',
                           'milestone', 'percent_complete', 'text1', 'text2', 'text3',
                           'flag1', 'flag2'.
            include_tasks: If true, include task list per group (default false).
        """
        app  = get_app()
        proj = get_proj(app)

        groups = {}
        total  = 0

        for t in proj.Tasks:
            if t is None or t.Summary:
                continue
            total += 1

            td = task_to_dict(t, proj) if include_tasks else None

            if field == "resource":
                # Split comma-separated resource names
                names = [n.strip() for n in (t.ResourceNames or "").split(",") if n.strip()]
                if not names:
                    names = ["(unassigned)"]
                keys = names
            elif field == "percent_complete":
                pct = t.PercentComplete
                if pct == 0:
                    keys = ["0%"]
                elif pct <= 25:
                    keys = ["1-25%"]
                elif pct <= 50:
                    keys = ["26-50%"]
                elif pct <= 75:
                    keys = ["51-75%"]
                elif pct < 100:
                    keys = ["76-99%"]
                else:
                    keys = ["100%"]
            elif field in ("rag", "text1"):
                keys = [(t.Text1 or "").strip() or "(blank)"]
            elif field == "text2":
                keys = [(t.Text2 or "").strip() or "(blank)"]
            elif field == "text3":
                keys = [(t.Text3 or "").strip() or "(blank)"]
            elif field == "outline_level":
                keys = [str(t.OutlineLevel)]
            elif field == "critical":
                keys = [str(bool(t.Critical))]
            elif field == "milestone":
                keys = [str(bool(t.Milestone))]
            elif field == "flag1":
                keys = [str(bool(t.Flag1))]
            elif field == "flag2":
                keys = [str(bool(t.Flag2))]
            else:
                keys = [str(getattr(t, field, "(unknown)"))]

            for k in keys:
                if k not in groups:
                    groups[k] = {"value": k, "count": 0}
                    if include_tasks:
                        groups[k]["tasks"] = []
                groups[k]["count"] += 1
                if include_tasks and td:
                    groups[k]["tasks"].append(td)

        result = sorted(groups.values(), key=lambda g: g["count"], reverse=True)

        return json.dumps({
            "field":       field,
            "groups":      result,
            "total_tasks": total,
        }, indent=2)


    @mcp.tool()
    def apply_filter(filter_name: str) -> str:
        """
        Apply MS Project's built-in or custom named filter to the Gantt view.
        Use 'All Tasks' to clear any active filter.

        Args:
            filter_name: Name of the filter (e.g. 'Critical', 'Incomplete Tasks', 'All Tasks').
        """
        app = get_app()

        try:
            app.FilterApply(filter_name)
        except Exception as e:
            return json.dumps({"error": f"Failed to apply filter '{filter_name}': {e}"})

        return json.dumps({
            "status": "applied",
            "filter": filter_name,
        }, indent=2)


    @mcp.tool()
    def export_csv(output_path: str, columns_json: str = "", filters_json: str = "") -> str:
        """
        Export filtered task data to CSV for PowerBI / Excel dashboards.

        Args:
            output_path:  Full path for the output CSV file (required).
            columns_json: JSON list of column names to include (optional, default: standard set).
                          Available: any key from task_to_dict output.
            filters_json: JSON object with filter criteria (same format as filter_tasks).
        """
        output_path = validate_safe_path(output_path)
        if is_dry_run():
            return dry_run_response("export_csv", {"output_path": output_path})
        import csv

        app  = get_app()
        proj = get_proj(app)

        # Default columns
        default_cols = ["unique_id", "name", "outline_level", "start", "finish",
                        "duration_days", "percent_complete", "resource_names", "rag", "critical"]

        columns = default_cols
        if columns_json:
            columns = json.loads(columns_json)

        # Apply filters if provided
        tasks = []
        if filters_json:
            f = json.loads(filters_json)
            # Reuse filter_tasks logic inline
            result = json.loads(filter_tasks(json.dumps(f)))
            tasks = result.get("tasks", [])
        else:
            for t in proj.Tasks:
                if t is not None:
                    tasks.append(task_to_dict(t, proj))

        # Write CSV
        with open(output_path, "w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            writer.writerow(columns)
            for task in tasks:
                row = [task.get(col, "") for col in columns]
                writer.writerow(row)

        return json.dumps({
            "status":  "exported",
            "path":    output_path,
            "rows":    len(tasks),
            "columns": columns,
        }, indent=2)
