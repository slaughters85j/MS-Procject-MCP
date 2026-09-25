"""
Structured task filtering, grouping, named view filters, and CSV export of filtered tasks.

filter_tasks and export_csv share one matcher (_matching_tasks) that rejects unknown filter
keys, so a typo can never silently widen a result set that later feeds a bulk write.
"""

import csv
import json

from ..com_helpers import get_app, get_proj, _parse_date, _to_naive, task_to_dict, assigned_resource_names
from ..guards import validate_safe_path, prepare_task_response, _RESPONSE_MGMT

_TEXT_KEYS = {"rag": "Text1", "text1": "Text1", "text2": "Text2", "text3": "Text3"}
_BOOL_KEYS = {"critical": "Critical", "milestone": "Milestone", "active": "Active",
              "summary": "Summary", "flag1": "Flag1", "flag2": "Flag2"}
_DATE_KEYS = {"start_after": ("Start", 1), "start_before": ("Start", -1),
              "finish_after": ("Finish", 1), "finish_before": ("Finish", -1)}
_CONTROL_KEYS = {"sort_by", "sort_desc", "limit", "offset"}
FILTER_KEYS = set(_TEXT_KEYS) | set(_BOOL_KEYS) | set(_DATE_KEYS) | _CONTROL_KEYS | {
    "resource", "min_pct", "max_pct", "outline_level", "name_contains"}
GROUP_FIELDS = ("rag", "resource", "outline_level", "critical", "milestone", "percent_complete",
                "text1", "text2", "text3", "flag1", "flag2")
DEFAULT_COLUMNS = ["unique_id", "name", "outline_level", "start", "finish",
                   "duration_days", "percent_complete", "resource_names", "rag", "critical"]
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _predicates(f):
    """Build predicate functions from a filter object. Raises ValueError on unknown keys or bad values."""
    unknown = sorted(set(f) - FILTER_KEYS)
    if unknown:
        raise ValueError(f"Unknown filter key(s) {unknown}. Valid keys: {sorted(FILTER_KEYS)}.")
    preds = []
    for key, attr in _TEXT_KEYS.items():
        if key in f:
            preds.append(lambda t, a=attr, v=str(f[key]).strip().lower(): (getattr(t, a) or "").strip().lower() == v)
    for key, attr in _BOOL_KEYS.items():
        if key in f:
            if not isinstance(f[key], bool):
                raise ValueError(f"Filter '{key}' must be true or false.")
            preds.append(lambda t, a=attr, v=f[key]: bool(getattr(t, a)) == v)
    for key, (attr, sign) in _DATE_KEYS.items():
        if key in f:
            d = _parse_date(f[key])
            if sign > 0:
                preds.append(lambda t, a=attr, d=d: _to_naive(getattr(t, a)) is not None and _to_naive(getattr(t, a)) >= d)
            else:
                d = d.replace(hour=23, minute=59)
                preds.append(lambda t, a=attr, d=d: _to_naive(getattr(t, a)) is not None and _to_naive(getattr(t, a)) <= d)
    if "resource" in f:
        preds.append(lambda t, v=str(f["resource"]).strip().lower(): v in [n.lower() for n in assigned_resource_names(t)])
    if "min_pct" in f:
        preds.append(lambda t, v=float(f["min_pct"]): t.PercentComplete >= v)
    if "max_pct" in f:
        preds.append(lambda t, v=float(f["max_pct"]): t.PercentComplete <= v)
    if "outline_level" in f:
        preds.append(lambda t, v=int(f["outline_level"]): t.OutlineLevel == v)
    if "name_contains" in f:
        preds.append(lambda t, v=str(f["name_contains"]).lower(): v in t.Name.lower())
    return preds


def _matching_tasks(proj, f):
    """All tasks matching filter object f, as task dicts, sorted if requested."""
    preds = _predicates(f)
    matched = [task_to_dict(t, proj) for t in proj.Tasks if t is not None and all(p(t) for p in preds)]
    sort_by = f.get("sort_by", "")
    if sort_by:
        if matched and sort_by not in matched[0]:
            raise ValueError(f"Unknown sort_by '{sort_by}'. Use a task field such as {sorted(matched[0])[:12]}.")
        matched.sort(key=lambda x: (x.get(sort_by) is None, x.get(sort_by) if x.get(sort_by) is not None else ""),
                     reverse=bool(f.get("sort_desc", False)))
    return matched


def _parse_filters(filters_json):
    f = json.loads(filters_json) if filters_json else {}
    if not isinstance(f, dict):
        raise ValueError("filters_json must be a JSON object.")
    return f


def _csv_safe(value):
    """Neutralise spreadsheet formula injection in text cells."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def register_task_filter_tools(mcp):
    """Register the task filter tools on the FastMCP instance."""

    @mcp.tool()
    def filter_tasks(filters_json: str) -> str:
        """
        AND-logic filtering across task fields with sort and pagination. Unknown keys are rejected.

        Args:
            filters_json: JSON string with filter keys (all optional):
                rag, resource (exact name), start_after, start_before, finish_after, finish_before,
                min_pct, max_pct, outline_level, critical (bool), milestone (bool),
                active (bool), summary (bool), name_contains,
                text1, text2, text3, flag1 (bool), flag2 (bool),
                sort_by (field name), sort_desc (bool), limit (int, 0 = all), offset (int).
                Example: '{"rag": "Red", "critical": true, "limit": 20}'
        """
        f = _parse_filters(filters_json)
        app  = get_app()
        proj = get_proj(app)
        matched = _matching_tasks(proj, f)
        offset, limit = int(f.get("offset", 0)), int(f.get("limit", 0))
        if offset < 0 or limit < 0:
            raise ValueError("offset and limit cannot be negative (limit 0 = all).")
        if _RESPONSE_MGMT:
            return prepare_task_response(matched, offset=offset, limit=limit if limit > 0 else -1)
        page = matched[offset:offset + limit] if limit else matched[offset:]
        return json.dumps({"total_matching": len(matched), "returned": len(page), "offset": offset,
                           "limit": limit or len(matched), "tasks": page}, indent=2)

    @mcp.tool()
    def group_tasks_by(field: str, include_tasks: bool = False) -> str:
        """
        Group non-summary tasks by a field and return counts per group.

        Args:
            field:         One of 'rag', 'resource' (alias 'resource_names'), 'outline_level',
                           'critical', 'milestone', 'percent_complete', 'text1', 'text2',
                           'text3', 'flag1', 'flag2'.
            include_tasks: If true, include task list per group (default false).
        """
        field = {"resource_names": "resource"}.get(field.strip().lower(), field.strip().lower())
        if field not in GROUP_FIELDS:
            return json.dumps({"error": f"Cannot group by '{field}'. Use one of: {', '.join(GROUP_FIELDS)}."})
        app  = get_app()
        proj = get_proj(app)
        groups, total = {}, 0
        for t in proj.Tasks:
            if t is None or t.Summary:
                continue
            total += 1
            if field == "resource":
                keys = assigned_resource_names(t) or ["(unassigned)"]
            elif field == "percent_complete":
                pct = t.PercentComplete
                keys = ["0%" if pct == 0 else "1-25%" if pct <= 25 else "26-50%" if pct <= 50
                        else "51-75%" if pct <= 75 else "76-99%" if pct < 100 else "100%"]
            elif field in _TEXT_KEYS:
                keys = [(getattr(t, _TEXT_KEYS[field]) or "").strip() or "(blank)"]
            elif field in _BOOL_KEYS:
                keys = [str(bool(getattr(t, _BOOL_KEYS[field])))]
            else:
                keys = [str(t.OutlineLevel)]
            td = task_to_dict(t, proj) if include_tasks else None
            for k in keys:
                g = groups.setdefault(k, {"value": k, "count": 0, **({"tasks": []} if include_tasks else {})})
                g["count"] += 1
                if td:
                    g["tasks"].append(td)
        return json.dumps({"field": field, "groups": sorted(groups.values(), key=lambda g: g["count"], reverse=True),
                           "total_tasks": total}, indent=2)

    @mcp.tool()
    def apply_filter(filter_name: str) -> str:
        """
        Apply MS Project's built-in or custom named filter to the Gantt view.
        Use 'All Tasks' to clear any active filter. (Tools that edit tasks are not affected
        by the view filter.)

        Args:
            filter_name: Name of the filter (e.g. 'Critical', 'Incomplete Tasks', 'All Tasks').
        """
        app = get_app()
        app.FilterApply(filter_name)
        return json.dumps({"status": "applied", "filter": filter_name}, indent=2)

    @mcp.tool()
    def export_csv(output_path: str, columns_json: str = "", filters_json: str = "") -> str:
        """
        Export (optionally filtered) task data to CSV for PowerBI / Excel dashboards.
        Text cells starting with = + - @ are prefixed with ' so spreadsheets do not run them.

        Args:
            output_path:  Full path for the output CSV file (required).
            columns_json: JSON list of column names (optional, default: a standard set).
                          Any key from get_task output is accepted; unknown names are rejected.
            filters_json: JSON object with filter criteria (same keys as filter_tasks).
        """
        output_path = validate_safe_path(output_path)
        columns = json.loads(columns_json) if columns_json else DEFAULT_COLUMNS
        if not isinstance(columns, list) or not columns:
            raise ValueError("columns_json must be a non-empty JSON array of column names.")
        f = _parse_filters(filters_json)
        f.pop("limit", None)
        f.pop("offset", None)
        app  = get_app()
        proj = get_proj(app)
        tasks = _matching_tasks(proj, f)
        valid = set(tasks[0]) if tasks else set(DEFAULT_COLUMNS)
        unknown = [c for c in columns if c not in valid]
        if unknown:
            raise ValueError(f"Unknown column(s) {unknown}. Available: {sorted(valid)}.")
        with open(output_path, "w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            writer.writerow(columns)
            for task in tasks:
                writer.writerow([_csv_safe(task.get(col, "")) for col in columns])
        return json.dumps({"status": "exported", "path": output_path, "rows": len(tasks), "columns": columns}, indent=2)
