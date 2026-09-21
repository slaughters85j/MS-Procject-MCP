"""
Resource workload, availability, leveling, and cost rate tables.
"""

import json

from ..com_helpers import get_app, get_proj, _parse_date, _fmt_date
from ..guards import is_dry_run, dry_run_response


def register_resource_planning_tools(mcp):
    """Register the resource planning tools on the FastMCP instance."""

    @mcp.tool()
    def get_resource_workload(resource_name: str, start_date: str = "", end_date: str = "") -> str:
        """
        Resource allocation view with conflict detection.
        Shows all assignments for a resource and identifies overlapping assignments.

        Args:
            resource_name: Resource name (case-insensitive exact match).
            start_date:    Filter assignments starting after this date (YYYY-MM-DD, optional).
            end_date:      Filter assignments ending before this date (YYYY-MM-DD, optional).
        """
        app  = get_app()
        proj = get_proj(app)

        # Find resource
        resource = None
        for r in proj.Resources:
            if r is not None and r.Name.lower() == resource_name.lower():
                resource = r
                break

        if resource is None:
            # List available resources
            avail = []
            for r in proj.Resources:
                if r is not None:
                    avail.append(r.Name)
            return json.dumps({"error": f"Resource '{resource_name}' not found. Available: {avail}"})

        filter_start = _parse_date(start_date) if start_date else None
        filter_end   = _parse_date(end_date) if end_date else None

        assignments = []
        for a in resource.Assignments:
            try:
                a_start  = a.Start
                a_finish = a.Finish
                task     = a.Task

                if filter_start and a_finish and a_finish < filter_start:
                    continue
                if filter_end and a_start and a_start > filter_end:
                    continue

                work_hours = 0
                try:
                    work_hours = round(a.Work / 60, 2)  # minutes to hours
                except Exception:
                    pass

                assignments.append({
                    "task_unique_id": task.UniqueID if task else None,
                    "task_name":      task.Name if task else "(unknown)",
                    "start":          _fmt_date(a_start),
                    "finish":         _fmt_date(a_finish),
                    "units":          a.Units,
                    "work_hours":     work_hours,
                })
            except Exception:
                continue

        # Conflict detection: find overlapping date ranges
        conflicts = []
        for i in range(len(assignments)):
            for j in range(i + 1, len(assignments)):
                a = assignments[i]
                b = assignments[j]
                if a["start"] and a["finish"] and b["start"] and b["finish"]:
                    if a["start"] <= b["finish"] and b["start"] <= a["finish"]:
                        overlap_start = max(a["start"], b["start"])
                        overlap_finish = min(a["finish"], b["finish"])
                        combined = (a.get("units") or 0) + (b.get("units") or 0)
                        conflicts.append({
                            "task_a":          a["task_name"],
                            "task_b":          b["task_name"],
                            "overlap_start":   overlap_start,
                            "overlap_finish":  overlap_finish,
                            "combined_units":  combined,
                        })

        overallocated = False
        try:
            overallocated = bool(resource.Overallocated)
        except Exception:
            pass

        max_units = 1.0
        try:
            max_units = resource.MaxUnits
        except Exception:
            pass

        return json.dumps({
            "resource":      resource.Name,
            "overallocated": overallocated,
            "max_units":     max_units,
            "assignments":   assignments,
            "conflicts":     conflicts,
        }, indent=2)


    @mcp.tool()
    def level_resources() -> str:
        """
        Run MS Project's built-in resource leveling algorithm.
        WARNING: This may shift task dates. Save a baseline first if tracking variance.
        """
        if is_dry_run():
            return dry_run_response("level_resources", {})
        app  = get_app()
        proj = get_proj(app)

        app.LevelNow()
        app.FileSave()

        return json.dumps({
            "status":  "leveled",
            "project": proj.Name,
        }, indent=2)


    @mcp.tool()
    def get_resource_availability(
        resource_name: str,
        start_date:    str,
        end_date:      str,
        timescale:     str = "weekly",
    ) -> str:
        """
        Show resource allocation vs capacity per period. Shows max units, allocated
        work, and free capacity windows.

        Args:
            resource_name: Name of the resource.
            start_date:    Period start as YYYY-MM-DD.
            end_date:      Period end as YYYY-MM-DD.
            timescale:     'daily', 'weekly', or 'monthly' (default 'weekly').
        """
        app  = get_app()
        proj = get_proj(app)

        TIMESCALE_MAP = {"daily": 3, "weekly": 4, "monthly": 5}
        ts = TIMESCALE_MAP.get(timescale.lower())
        if ts is None:
            return json.dumps({"error": f"Unknown timescale '{timescale}'. Use: daily, weekly, monthly."})

        res = None
        for r in proj.Resources:
            if r is not None and r.Name and r.Name.lower() == resource_name.lower():
                res = r
                break
        if res is None:
            return json.dumps({"error": f"Resource '{resource_name}' not found."})

        sd = _parse_date(start_date)
        ed = _parse_date(end_date)

        max_units = res.MaxUnits  # e.g. 1.0 = 100%

        periods = []
        try:
            # Resource TimeScaleData types differ from Task types:
            # Type 13 = pjResourceTimescaledWork (minutes), Type 4 = Availability (units)
            tsd = res.TimeScaleData(sd, ed, 13, ts)
            for item in tsd:
                try:
                    val = item.Value
                    allocated_hrs = float(val) / 60.0 if val else 0.0
                except Exception:
                    allocated_hrs = 0.0
                periods.append({
                    "start":          _fmt_date(item.StartDate),
                    "end":            _fmt_date(item.EndDate),
                    "allocated_hours": round(allocated_hrs, 2),
                })
        except Exception as e:
            return json.dumps({"error": f"TimeScaleData failed: {e}"})

        return json.dumps({
            "resource":  res.Name,
            "max_units": max_units,
            "timescale": timescale,
            "periods":   periods,
        }, indent=2)


    @mcp.tool()
    def get_resource_rate_tables(resource_name: str) -> str:
        """
        Get cost rate tables (A through E) for a resource.

        Args:
            resource_name: Name of the resource.
        """
        app  = get_app()
        proj = get_proj(app)

        res = None
        for r in proj.Resources:
            if r is not None and r.Name and r.Name.lower() == resource_name.lower():
                res = r
                break
        if res is None:
            return json.dumps({"error": f"Resource '{resource_name}' not found."})

        tables = {}
        TABLE_NAMES = ["A", "B", "C", "D", "E"]

        for idx, tname in enumerate(TABLE_NAMES):
            try:
                table = res.CostRateTables(idx + 1)
                rates = []
                for pay_rate in table.PayRates:
                    rates.append({
                        "effective_date":  _fmt_date(pay_rate.EffectiveDate),
                        "standard_rate":   str(pay_rate.StandardRate),
                        "overtime_rate":   str(pay_rate.OvertimeRate),
                        "cost_per_use":    float(pay_rate.CostPerUse) if pay_rate.CostPerUse else 0.0,
                    })
                tables[tname] = rates
            except Exception:
                tables[tname] = []

        return json.dumps({
            "resource": res.Name,
            "tables":   tables,
        }, indent=2)


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
        app  = get_app()
        proj = get_proj(app)

        TABLE_MAP = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
        tbl_idx = TABLE_MAP.get(table.upper())
        if tbl_idx is None:
            return json.dumps({"error": f"Invalid table '{table}'. Use A-E."})

        res = None
        for r in proj.Resources:
            if r is not None and r.Name and r.Name.lower() == resource_name.lower():
                res = r
                break
        if res is None:
            return json.dumps({"error": f"Resource '{resource_name}' not found."})

        try:
            rate_table = res.CostRateTables(tbl_idx)
            pay_rates  = rate_table.PayRates

            if effective_date:
                # Add a new rate entry with effective date
                ed = _parse_date(effective_date)
                new_rate = pay_rates.Add(ed)
                if standard_rate:
                    new_rate.StandardRate = standard_rate
                if overtime_rate:
                    new_rate.OvertimeRate = overtime_rate
                if cost_per_use >= 0:
                    new_rate.CostPerUse = cost_per_use
            else:
                # Update the first (default) rate entry
                first = pay_rates(1)
                if standard_rate:
                    first.StandardRate = standard_rate
                if overtime_rate:
                    first.OvertimeRate = overtime_rate
                if cost_per_use >= 0:
                    first.CostPerUse = cost_per_use

            app.FileSave()
            return json.dumps({
                "status":   "updated",
                "resource": res.Name,
                "table":    table.upper(),
                "standard_rate": standard_rate or "(unchanged)",
                "overtime_rate": overtime_rate or "(unchanged)",
                "cost_per_use":  cost_per_use if cost_per_use >= 0 else "(unchanged)",
            }, indent=2)

        except Exception as e:
            return json.dumps({"error": f"Failed to update rate table: {e}"})
