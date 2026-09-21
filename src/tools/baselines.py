"""
Baseline capture, clearing, comparison, and variance reporting.
"""

import json

from ..com_helpers import get_app, get_proj, _get_mpd, _fmt_date, _to_naive
from ..guards import is_dry_run, dry_run_response


def register_baselines_tools(mcp):
    """Register the baselines tools on the FastMCP instance."""

    @mcp.tool()
    def save_baseline(baseline_number: int = 0, all_tasks: bool = True) -> str:
        """
        Save a baseline snapshot for earned value and variance tracking.

        Args:
            baseline_number: 0 to 10 (Baseline, Baseline1 through Baseline10). Default 0.
            all_tasks:       True to baseline all tasks (default), False for selected only.
        """
        if baseline_number < 0 or baseline_number > 10:
            return json.dumps({"error": "baseline_number must be 0-10."})
        if is_dry_run():
            return dry_run_response("save_baseline", {"baseline_number": baseline_number, "all_tasks": all_tasks})

        app  = get_app()
        proj = get_proj(app)

        task_count = sum(1 for t in proj.Tasks if t is not None)

        app.BaselineSave(All=all_tasks, Copy=baseline_number, Into=baseline_number)
        app.FileSave()

        return json.dumps({
            "status":          "saved",
            "baseline_number": baseline_number,
            "all_tasks":       all_tasks,
            "tasks_baselined": task_count if all_tasks else "selected",
        }, indent=2)


    @mcp.tool()
    def clear_baseline(baseline_number: int = 0, all_tasks: bool = True) -> str:
        """
        Clear a previously saved baseline.

        Args:
            baseline_number: 0 to 10. Default 0.
            all_tasks:       True to clear for all tasks (default).
        """
        if baseline_number < 0 or baseline_number > 10:
            return json.dumps({"error": "baseline_number must be 0-10."})
        if is_dry_run():
            return dry_run_response("clear_baseline", {"baseline_number": baseline_number, "all_tasks": all_tasks})

        app = get_app()
        app.BaselineClear(All=all_tasks, From=baseline_number)
        app.FileSave()

        return json.dumps({
            "status":          "cleared",
            "baseline_number": baseline_number,
        }, indent=2)


    @mcp.tool()
    def compare_baselines(baseline_a: int = 0, baseline_b: int = -1) -> str:
        """
        Variance report between two baselines, or baseline vs current schedule.

        Args:
            baseline_a: First baseline number (0-10). Default 0.
            baseline_b: Second baseline number (0-10), or -1 for current schedule (default).
        """
        if baseline_a < 0 or baseline_a > 10:
            return json.dumps({"error": "baseline_a must be 0-10."})
        if baseline_b < -1 or baseline_b > 10:
            return json.dumps({"error": "baseline_b must be -1 to 10 (-1 = current schedule)."})

        app  = get_app()
        proj = get_proj(app)

        def _bl_attr(n, suffix):
            if n == 0:
                return f"Baseline{suffix}"
            return f"Baseline{n}{suffix}"

        tasks = []
        tasks_with_variance = 0
        total_finish_variance = 0
        max_slippage = 0
        total_tasks = 0

        for t in proj.Tasks:
            if t is None or t.Summary:
                continue
            total_tasks += 1

            try:
                a_start  = _to_naive(getattr(t, _bl_attr(baseline_a, "Start"), None))
                a_finish = _to_naive(getattr(t, _bl_attr(baseline_a, "Finish"), None))
            except Exception:
                a_start = a_finish = None

            if baseline_b == -1:
                b_start  = _to_naive(t.Start)
                b_finish = _to_naive(t.Finish)
            else:
                try:
                    b_start  = _to_naive(getattr(t, _bl_attr(baseline_b, "Start"), None))
                    b_finish = _to_naive(getattr(t, _bl_attr(baseline_b, "Finish"), None))
                except Exception:
                    b_start = b_finish = None

            start_delta = finish_delta = None
            if a_start and b_start:
                try:
                    start_delta = (b_start - a_start).days
                except Exception:
                    pass
            if a_finish and b_finish:
                try:
                    finish_delta = (b_finish - a_finish).days
                except Exception:
                    pass

            if finish_delta is not None and finish_delta != 0:
                tasks_with_variance += 1
                total_finish_variance += finish_delta
                if finish_delta > max_slippage:
                    max_slippage = finish_delta

            tasks.append({
                "unique_id":    t.UniqueID,
                "name":         t.Name,
                "a_start":      _fmt_date(a_start),
                "a_finish":     _fmt_date(a_finish),
                "b_start":      _fmt_date(b_start),
                "b_finish":     _fmt_date(b_finish),
                "start_delta":  start_delta,
                "finish_delta": finish_delta,
            })

        # Sort by finish variance desc (worst slippages first)
        tasks.sort(key=lambda x: x["finish_delta"] if x["finish_delta"] is not None else 0, reverse=True)

        return json.dumps({
            "baseline_a": baseline_a,
            "baseline_b": baseline_b if baseline_b >= 0 else "current",
            "summary": {
                "total_tasks":          total_tasks,
                "tasks_with_variance":  tasks_with_variance,
                "avg_finish_variance":  round(total_finish_variance / tasks_with_variance, 1) if tasks_with_variance else 0,
                "max_slippage":         max_slippage,
            },
            "tasks": tasks,
        }, indent=2)


    @mcp.tool()
    def get_variance_report(baseline: int = 0) -> str:
        """
        Schedule and cost variance per task compared to a baseline.

        Args:
            baseline: Baseline number (0-10). Default 0.
        """
        app  = get_app()
        proj = get_proj(app)
        mpd  = _get_mpd(proj)

        # Baseline property name mapping
        BL_START  = f"Baseline{'' if baseline == 0 else baseline}Start"
        BL_FINISH = f"Baseline{'' if baseline == 0 else baseline}Finish"
        BL_COST   = f"Baseline{'' if baseline == 0 else baseline}Cost"

        tasks = []
        for t in proj.Tasks:
            if t is None or t.Summary:
                continue
            try:
                bl_start  = getattr(t, BL_START, None)
                bl_finish = getattr(t, BL_FINISH, None)
                bl_cost   = getattr(t, BL_COST, 0) or 0

                sv_days = round(t.StartVariance / mpd, 2) if t.StartVariance else 0
                fv_days = round(t.FinishVariance / mpd, 2) if t.FinishVariance else 0
                cv      = round((t.Cost or 0) - bl_cost, 2)

                tasks.append({
                    "unique_id":        t.UniqueID,
                    "name":             t.Name,
                    "start":            _fmt_date(t.Start),
                    "finish":           _fmt_date(t.Finish),
                    "baseline_start":   _fmt_date(bl_start),
                    "baseline_finish":  _fmt_date(bl_finish),
                    "start_variance_days":  sv_days,
                    "finish_variance_days": fv_days,
                    "cost":             round(t.Cost or 0, 2),
                    "baseline_cost":    round(bl_cost, 2),
                    "cost_variance":    cv,
                })
            except Exception:
                continue

        # Filter to only tasks with actual variance
        with_variance = [t for t in tasks if t["start_variance_days"] != 0 or t["finish_variance_days"] != 0 or t["cost_variance"] != 0]

        return json.dumps({
            "baseline":       baseline,
            "total_tasks":    len(tasks),
            "with_variance":  len(with_variance),
            "tasks":          with_variance if with_variance else tasks[:50],
        }, indent=2)
