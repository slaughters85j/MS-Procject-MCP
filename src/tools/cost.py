"""
Cost reporting: earned value, cost summary, and timephased data.
"""

import json
from typing import Literal

from ..com_helpers import get_app, get_proj, _fmt_date, _find_task
from ..com_write import parse_iso, to_com_date, TIMESCALES

# PjTaskTimescaledData values (read from the Project type library).
TASK_TIMESCALED_DATA = {
    "work": 0, "baseline_work": 1, "actual_work": 2, "cost": 5, "baseline_cost": 6,
    "actual_cost": 7, "cumulative_work": 176, "cumulative_cost": 177,
    "remaining_cumulative_work": 1343,
}


def register_cost_tools(mcp):
    """Register the cost tools on the FastMCP instance."""

    @mcp.tool()
    def get_earned_value() -> str:
        """
        Return earned value metrics for all non-summary tasks.
        Requires a saved baseline and progress (% complete) to return meaningful data.
        Fields: BCWS (PV), BCWP (EV), ACWP (AC), SV, CV, plus SPI and CPI.
        """
        app  = get_app()
        proj = get_proj(app)

        tasks = []
        totals = {"bcws": 0, "bcwp": 0, "acwp": 0, "sv": 0, "cv": 0}

        for t in proj.Tasks:
            if t is None or t.Summary:
                continue

            try:
                bcws = float(t.BCWS) if t.BCWS else 0
            except Exception:
                bcws = 0
            try:
                bcwp = float(t.BCWP) if t.BCWP else 0
            except Exception:
                bcwp = 0
            try:
                acwp = float(t.ACWP) if t.ACWP else 0
            except Exception:
                acwp = 0
            try:
                sv = float(t.SV) if t.SV else 0
            except Exception:
                sv = 0
            try:
                cv = float(t.CV) if t.CV else 0
            except Exception:
                cv = 0

            totals["bcws"] += bcws
            totals["bcwp"] += bcwp
            totals["acwp"] += acwp
            totals["sv"]   += sv
            totals["cv"]   += cv

            tasks.append({
                "unique_id": t.UniqueID,
                "name":      t.Name,
                "bcws":      bcws,
                "bcwp":      bcwp,
                "acwp":      acwp,
                "sv":        sv,
                "cv":        cv,
            })

        # Derived indices
        spi = round(totals["bcwp"] / totals["bcws"], 3) if totals["bcws"] else 0
        cpi = round(totals["bcwp"] / totals["acwp"], 3) if totals["acwp"] else 0

        if totals["bcws"] == 0 and totals["bcwp"] == 0:
            warning = "No earned value data. Ensure a baseline is saved and progress is entered."
        else:
            warning = None

        result = {
            "project_totals": {
                "bcws": totals["bcws"],
                "bcwp": totals["bcwp"],
                "acwp": totals["acwp"],
                "sv":   totals["sv"],
                "cv":   totals["cv"],
                "spi":  spi,
                "cpi":  cpi,
            },
            "tasks": tasks,
        }
        if warning:
            result["warning"] = warning

        return json.dumps(result, indent=2)


    @mcp.tool()
    def get_cost_summary() -> str:
        """
        Budget rollup with cost fields.
        Returns project cost totals, cost breakdown by resource, and tasks with cost data.
        Requires cost data to be entered on tasks or resources.
        """
        app  = get_app()
        proj = get_proj(app)

        totals = {"cost": 0, "actual_cost": 0, "remaining_cost": 0, "baseline_cost": 0}
        by_resource = {}
        tasks_with_cost = []

        for t in proj.Tasks:
            if t is None or t.Summary:
                continue

            cost = actual = remaining = baseline = 0
            try:
                cost = float(t.Cost) if t.Cost else 0
            except Exception:
                pass
            try:
                actual = float(t.ActualCost) if t.ActualCost else 0
            except Exception:
                pass
            try:
                remaining = float(t.RemainingCost) if t.RemainingCost else 0
            except Exception:
                pass
            try:
                baseline = float(t.BaselineCost) if t.BaselineCost else 0
            except Exception:
                pass

            totals["cost"] += cost
            totals["actual_cost"] += actual
            totals["remaining_cost"] += remaining
            totals["baseline_cost"] += baseline

            if cost > 0:
                tasks_with_cost.append({
                    "unique_id":      t.UniqueID,
                    "name":           t.Name,
                    "cost":           cost,
                    "actual_cost":    actual,
                    "remaining_cost": remaining,
                    "baseline_cost":  baseline,
                })

        # Cost by resource, summed from assignments (a resource's cost is the sum of its
        # assignments). Reading Resource.Cost makes Project recompute and marks the file unsaved.
        for t in proj.Tasks:
            if t is None or t.Summary:
                continue
            for a in t.Assignments:
                entry = by_resource.setdefault(a.ResourceName, {"cost": 0.0, "actual_cost": 0.0})
                entry["cost"] += float(a.Cost or 0)
                entry["actual_cost"] += float(a.ActualCost or 0)
        by_resource = {k: v for k, v in by_resource.items() if v["cost"] > 0 or v["actual_cost"] > 0}

        totals["variance"] = totals["baseline_cost"] - totals["cost"]

        return json.dumps({
            "project": proj.Name,
            "totals":  totals,
            "by_resource":     list({"name": k, **v} for k, v in by_resource.items()),
            "tasks_with_cost": tasks_with_cost,
        }, indent=2)


    @mcp.tool()
    def get_timephased_data(
        unique_id:  int,
        start_date: str,
        end_date:   str,
        timescale:  Literal["daily", "weekly", "monthly"] = "weekly",
        data_type:  Literal["work", "cost", "actual_work", "actual_cost", "baseline_work",
                            "baseline_cost", "cumulative_work", "cumulative_cost",
                            "remaining_cumulative_work"] = "work",
    ) -> str:
        """
        Get period-by-period timephased data for a task. Essential for S-curves,
        resource loading charts, and cash flow forecasts. Work values are in minutes.

        Args:
            unique_id:  Task UniqueID.
            start_date: Period start as YYYY-MM-DD.
            end_date:   Period end as YYYY-MM-DD (not before start_date).
            timescale:  'daily', 'weekly', or 'monthly' (default 'weekly').
            data_type:  'work', 'cost', 'actual_work', 'actual_cost', 'baseline_work',
                        'baseline_cost', 'cumulative_work', 'cumulative_cost',
                        'remaining_cumulative_work' (default 'work').
        """
        app  = get_app()
        proj = get_proj(app)
        t = _find_task(proj, unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})
        if parse_iso(end_date, "end_date")[0] < parse_iso(start_date, "start_date")[0]:
            return json.dumps({"error": "end_date is before start_date."})

        tsd = t.TimeScaleData(to_com_date(proj, start_date, field="start_date"),
                              to_com_date(proj, end_date, end_of_day=True, field="end_date"),
                              TASK_TIMESCALED_DATA[data_type], TIMESCALES[timescale])
        periods = [{
            "start": _fmt_date(item.StartDate),
            "end":   _fmt_date(item.EndDate),
            "value": float(item.Value) if item.Value not in ("", None) else 0.0,
        } for item in tsd]
        return json.dumps({
            "unique_id": unique_id,
            "name":      t.Name,
            "data_type": data_type,
            "timescale": timescale,
            "periods":   periods,
        }, indent=2)
