"""
Cost reporting: earned value, cost summary, and timephased data.
"""

import json

from ..com_helpers import get_app, get_proj, _parse_date, _fmt_date, _find_task


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

        # Cost by resource
        try:
            for r in proj.Resources:
                if r is not None:
                    r_cost = 0
                    r_actual = 0
                    try:
                        r_cost = float(r.Cost) if r.Cost else 0
                    except Exception:
                        pass
                    try:
                        r_actual = float(r.ActualCost) if r.ActualCost else 0
                    except Exception:
                        pass
                    if r_cost > 0 or r_actual > 0:
                        by_resource[r.Name] = {"cost": r_cost, "actual_cost": r_actual}
        except Exception:
            pass

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
        timescale:  str = "weekly",
        data_type:  str = "work",
    ) -> str:
        """
        Get period-by-period timephased data for a task. Essential for S-curves,
        resource loading charts, and cash flow forecasts.

        Args:
            unique_id:  Task UniqueID.
            start_date: Period start as YYYY-MM-DD.
            end_date:   Period end as YYYY-MM-DD.
            timescale:  'daily', 'weekly', or 'monthly' (default 'weekly').
            data_type:  'work', 'cost', 'actual_work', 'actual_cost',
                        'remaining_work', 'baseline_work', 'baseline_cost' (default 'work').
        """
        app  = get_app()
        proj = get_proj(app)

        TIMESCALE_MAP = {"daily": 3, "weekly": 4, "monthly": 5}
        ts = TIMESCALE_MAP.get(timescale.lower())
        if ts is None:
            return json.dumps({"error": f"Unknown timescale '{timescale}'. Use: daily, weekly, monthly."})

        # pjTaskTimescaledWork=1, Cost=2, ActualWork=3, ActualCost=4,
        # RemainingWork=9, BaselineWork=22, BaselineCost=23
        TYPE_MAP = {
            "work": 1, "cost": 2, "actual_work": 3, "actual_cost": 4,
            "remaining_work": 9, "baseline_work": 22, "baseline_cost": 23,
        }
        dt = TYPE_MAP.get(data_type.lower())
        if dt is None:
            return json.dumps({"error": f"Unknown data_type '{data_type}'. Use: {list(TYPE_MAP.keys())}."})

        t = _find_task(proj, unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})

        sd = _parse_date(start_date)
        ed = _parse_date(end_date)
        if sd is None or ed is None:
            return json.dumps({"error": "Both start_date and end_date are required (YYYY-MM-DD)."})

        periods = []
        try:
            tsd = t.TimeScaleData(sd, ed, dt, ts)
            for item in tsd:
                val = item.Value
                periods.append({
                    "start": _fmt_date(item.StartDate),
                    "end":   _fmt_date(item.EndDate),
                    "value": float(val) if val else 0.0,
                })
        except Exception as e:
            return json.dumps({"error": f"TimeScaleData failed: {e}"})

        return json.dumps({
            "unique_id": unique_id,
            "name":      t.Name,
            "data_type": data_type,
            "timescale": timescale,
            "periods":   periods,
        }, indent=2)
