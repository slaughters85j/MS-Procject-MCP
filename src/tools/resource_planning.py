"""
Resource workload, availability, leveling, and cost rate tables.
"""

import json
from typing import Literal

from ..com_helpers import get_app, get_proj, _fmt_date, _to_naive
from ..com_write import parse_iso, to_com_date, commit, resolve_resource, invoke_positional, TIMESCALES

RATE_TABLES = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
PJ_RESOURCE_TIMESCALED_WORK = 13
PJ_RESOURCE_TIMESCALED_OVERALLOCATION = 42
PJ_TIMESCALE_MONTHS = 2


def _is_overallocated(proj, resource):
    """
    Overallocation anywhere in the project, from timescaled data. Reading the
    Resource.Overallocated property makes Project recompute and marks the file unsaved.
    """
    start, finish = proj.ProjectStart, proj.ProjectFinish
    data = resource.TimeScaleData(start, finish, PJ_RESOURCE_TIMESCALED_OVERALLOCATION, PJ_TIMESCALE_MONTHS)
    return any(item.Value not in ("", None, 0) for item in data)


def _date_range(start_date, end_date, required=False):
    """Parse an optional/required YYYY-MM-DD range. Raises ValueError on bad or reversed dates."""
    if required and not (start_date and end_date):
        raise ValueError("start_date and end_date are both required (YYYY-MM-DD).")
    start = parse_iso(start_date, "start_date")[0] if start_date else None
    end = parse_iso(end_date, "end_date")[0] if end_date else None
    if start and end and end < start:
        raise ValueError(f"end_date {end_date} is before start_date {start_date}.")
    return start, end


def register_resource_planning_tools(mcp):
    """Register the resource planning tools on the FastMCP instance."""

    @mcp.tool()
    def get_resource_workload(resource_name: str, start_date: str = "", end_date: str = "") -> str:
        """
        Resource allocation view with conflict detection.
        Shows the resource's assignments (optionally only those overlapping a date range)
        and identifies overlapping assignments.

        Args:
            resource_name: Resource name (case-insensitive exact match).
            start_date:    Only assignments finishing on/after this date (YYYY-MM-DD, optional).
            end_date:      Only assignments starting on/before this date (YYYY-MM-DD, optional).
        """
        app  = get_app()
        proj = get_proj(app)
        resource = resolve_resource(proj, resource_name)
        filter_start, filter_end = _date_range(start_date, end_date)
        if filter_end:
            filter_end = filter_end.replace(hour=23, minute=59)

        assignments = []
        for a in resource.Assignments:
            a_start, a_finish, task = _to_naive(a.Start), _to_naive(a.Finish), a.Task
            if filter_start and a_finish and a_finish < filter_start:
                continue
            if filter_end and a_start and a_start > filter_end:
                continue
            assignments.append({
                "task_unique_id": task.UniqueID if task else None,
                "task_name":      task.Name if task else "(unknown)",
                "start":          _fmt_date(a_start),
                "finish":         _fmt_date(a_finish),
                "units":          a.Units,
                "work_hours":     round((a.Work or 0) / 60, 2),
            })

        conflicts = []
        for i, a in enumerate(assignments):
            for b in assignments[i + 1:]:
                if a["start"] and a["finish"] and b["start"] and b["finish"] \
                        and a["start"] <= b["finish"] and b["start"] <= a["finish"]:
                    conflicts.append({
                        "task_a":         a["task_name"],
                        "task_b":         b["task_name"],
                        "overlap_start":  max(a["start"], b["start"]),
                        "overlap_finish": min(a["finish"], b["finish"]),
                        "combined_units": (a.get("units") or 0) + (b.get("units") or 0),
                    })

        return json.dumps({
            "resource":                 resource.Name,
            "overallocated":            _is_overallocated(proj, resource),  # anywhere in the project
            "max_units":                resource.MaxUnits,
            "assignments":              assignments,
            "conflicts":                conflicts,
        }, indent=2)

    @mcp.tool()
    def level_resources() -> str:
        """
        Run MS Project's built-in resource leveling algorithm.
        WARNING: This may shift task dates. Save a baseline first if tracking variance.
        """
        app  = get_app()
        proj = get_proj(app)
        app.LevelNow()
        commit(app, proj)
        return json.dumps({"status": "leveled", "project": proj.Name}, indent=2)

    @mcp.tool()
    def get_resource_availability(
        resource_name: str,
        start_date:    str,
        end_date:      str,
        timescale:     Literal["daily", "weekly", "monthly"] = "weekly",
    ) -> str:
        """
        Show resource allocation vs capacity per period: max units and allocated work per period.

        Args:
            resource_name: Name of the resource.
            start_date:    Period start as YYYY-MM-DD.
            end_date:      Period end as YYYY-MM-DD (not before start_date).
            timescale:     'daily', 'weekly', or 'monthly' (default 'weekly').
        """
        app  = get_app()
        proj = get_proj(app)
        _date_range(start_date, end_date, required=True)
        res = resolve_resource(proj, resource_name)
        tsd = res.TimeScaleData(to_com_date(proj, start_date, field="start_date"),
                                to_com_date(proj, end_date, end_of_day=True, field="end_date"),
                                PJ_RESOURCE_TIMESCALED_WORK, TIMESCALES[timescale])
        periods = [{
            "start":           _fmt_date(item.StartDate),
            "end":             _fmt_date(item.EndDate),
            "allocated_hours": round(float(item.Value) / 60.0, 2) if item.Value not in ("", None) else 0.0,
        } for item in tsd]
        return json.dumps({"resource": res.Name, "max_units": res.MaxUnits, "timescale": timescale,
                           "periods": periods}, indent=2)

    @mcp.tool()
    def get_resource_rate_tables(resource_name: str) -> str:
        """
        Get cost rate tables (A through E) for a resource.

        Args:
            resource_name: Name of the resource.
        """
        app  = get_app()
        proj = get_proj(app)
        res = resolve_resource(proj, resource_name)
        tables = {}
        for name, index in RATE_TABLES.items():
            tables[name] = [{
                "effective_date": _fmt_date(pay_rate.EffectiveDate),
                "standard_rate":  str(pay_rate.StandardRate),
                "overtime_rate":  str(pay_rate.OvertimeRate),
                "cost_per_use":   str(pay_rate.CostPerUse),  # formatted currency string, e.g. "$0.00"
            } for pay_rate in res.CostRateTables(index).PayRates]
        return json.dumps({"resource": res.Name, "tables": tables}, indent=2)

    @mcp.tool()
    def set_resource_rate_table(
        resource_name: str,
        table:         str = "A",
        standard_rate: str = "",
        overtime_rate: str = "",
        cost_per_use:  float = -1,
        effective_date: str = "",
    ) -> str:
        """
        Set or add a cost rate entry in a resource's rate table.

        Args:
            resource_name:  Name of the resource.
            table:          Rate table letter: A, B, C, D, or E (default A).
            standard_rate:  Standard rate as string, e.g. '50/h' or '400/d'.
            overtime_rate:  Overtime rate as string, e.g. '75/h'.
            cost_per_use:   Per-use cost (default -1 = don't change).
            effective_date: When this rate takes effect (YYYY-MM-DD). Empty = first entry.
        """
        tbl_idx = RATE_TABLES.get(table.upper())
        if tbl_idx is None:
            return json.dumps({"error": f"Invalid table '{table}'. Use A-E."})
        if not standard_rate and not overtime_rate and cost_per_use < 0:
            return json.dumps({"error": "Nothing to set: give standard_rate, overtime_rate or cost_per_use."})
        app  = get_app()
        proj = get_proj(app)
        res = resolve_resource(proj, resource_name)
        pay_rates = res.CostRateTables(tbl_idx).PayRates

        def row_for(date_text):
            return next((i for i in range(1, pay_rates.Count + 1)
                         if str(pay_rates(i).EffectiveDate)[:10] == date_text), None)

        index = row_for(effective_date) if effective_date else 1
        if index is None:
            # New row: rates go in as Add() arguments. Writing them to the object Add() returns
            # corrupts the table (it rewrites row 1 and leaves a bogus row behind).
            invoke_positional(pay_rates, "Add", to_com_date(proj, effective_date, field="effective_date"),
                              standard_rate or None, overtime_rate or None,
                              cost_per_use if cost_per_use >= 0 else None)
            index = row_for(effective_date)
        else:
            row = pay_rates(index)
            if standard_rate:
                row.StandardRate = standard_rate
            if overtime_rate:
                row.OvertimeRate = overtime_rate
            if cost_per_use >= 0:
                row.CostPerUse = cost_per_use
        entry = pay_rates(index)
        commit(app, proj)
        return json.dumps({
            "status":         "updated",
            "resource":       res.Name,
            "table":          table.upper(),
            "effective_date": _fmt_date(entry.EffectiveDate),
            "standard_rate":  str(entry.StandardRate),
            "overtime_rate":  str(entry.OvertimeRate),
            "cost_per_use":   str(entry.CostPerUse),
        }, indent=2)
