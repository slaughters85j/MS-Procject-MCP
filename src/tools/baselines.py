"""
Baseline capture, clearing, comparison, and variance reporting.

BaselineSave/BaselineClear take PjSaveBaselineFrom/To enum values, not baseline numbers:
pjCopyCurrent = 0, pjIntoBaseline = 0 and pjIntoBaseline1..10 = 11..20 (1..10 are the
Start1-10/Finish1-10 custom fields, which a plain baseline number would overwrite).
"""

import datetime
import json
from typing import List, Optional

from ..com_helpers import get_app, get_proj, _get_mpd, _fmt_date, _to_naive
from ..com_write import commit
from ..view_selection import rows_in_id_order, select_tasks

PJ_COPY_CURRENT = 0


def _into(n):
    """PjSaveBaselineTo value for baseline n (0-10)."""
    return 0 if n == 0 else 10 + n


def _attr(n, suffix):
    return f"Baseline{'' if n == 0 else n}{suffix}"


def _date_or_none(value):
    value = _to_naive(value)
    return value if isinstance(value, datetime.datetime) else None


def _baselined_count(proj, n):
    return sum(1 for t in proj.Tasks if t is not None and _date_or_none(getattr(t, _attr(n, "Start"))))


def _check_range(n, name, allow_current=False):
    low = -1 if allow_current else 0
    if not low <= n <= 10:
        raise ValueError(f"{name} must be 0-10{' or -1 (current schedule)' if allow_current else ''}.")


def _has_baseline(task, n):
    return _date_or_none(getattr(task, _attr(n, "Start"))) is not None


def _apply_baseline(save, baseline_number, all_tasks, unique_ids):
    """
    BaselineSave/BaselineClear for all tasks or for a verified selection of specific tasks.
    Selection-based calls never use whatever the user happens to have selected in the view.
    """
    _check_range(baseline_number, "baseline_number")
    if unique_ids is None and not all_tasks:
        raise ValueError("To baseline specific tasks, pass unique_ids (all_tasks=False alone would use "
                         "whatever is selected in MS Project).")
    app  = get_app()
    proj = get_proj(app)
    into = _into(baseline_number)
    targets = [t for t in proj.Tasks if t is not None and (unique_ids is None or t.UniqueID in set(unique_ids))]

    def run(all_tasks_flag):
        if save:
            app.BaselineSave(All=all_tasks_flag, Copy=PJ_COPY_CURRENT, Into=into)
        else:
            app.BaselineClear(All=all_tasks_flag, From=into)

    if unique_ids is None:
        run(True)
    else:
        with rows_in_id_order(app, proj):
            select_tasks(proj, app, unique_ids)
            run(False)
    wrong = [t.UniqueID for t in targets if _has_baseline(t, baseline_number) != save]
    if wrong:
        return json.dumps({"error": f"MS Project did not {'save' if save else 'clear'} baseline "
                                    f"{baseline_number} for UniqueIDs {wrong[:20]}."})
    commit(app, proj)
    return json.dumps({"status": "saved" if save else "cleared", "baseline_number": baseline_number,
                       "all_tasks": unique_ids is None,
                       ("tasks_baselined" if save else "tasks_cleared"): len(targets)}, indent=2)


def register_baselines_tools(mcp):
    """Register the baselines tools on the FastMCP instance."""

    @mcp.tool()
    def save_baseline(baseline_number: int = 0, all_tasks: bool = True,
                      unique_ids: Optional[List[int]] = None) -> str:
        """
        Save the current schedule into a baseline (Baseline, or Baseline1-10) for variance tracking.

        Args:
            baseline_number: 0 to 10 (Baseline, Baseline1 through Baseline10). Default 0.
            all_tasks:       True (default) baselines every task. Ignored when unique_ids is given.
            unique_ids:      Baseline only these tasks (by UniqueID).
        """
        return _apply_baseline(save=True, baseline_number=baseline_number, all_tasks=all_tasks, unique_ids=unique_ids)

    @mcp.tool()
    def clear_baseline(baseline_number: int = 0, all_tasks: bool = True,
                       unique_ids: Optional[List[int]] = None) -> str:
        """
        Clear a previously saved baseline.

        Args:
            baseline_number: 0 to 10. Default 0.
            all_tasks:       True (default) clears it for every task. Ignored when unique_ids is given.
            unique_ids:      Clear it only for these tasks (by UniqueID).
        """
        return _apply_baseline(save=False, baseline_number=baseline_number, all_tasks=all_tasks, unique_ids=unique_ids)

    @mcp.tool()
    def compare_baselines(baseline_a: int = 0, baseline_b: int = -1) -> str:
        """
        Variance report between two baselines, or baseline vs current schedule.
        Returns an error if a requested baseline has never been saved.

        Args:
            baseline_a: First baseline number (0-10). Default 0.
            baseline_b: Second baseline number (0-10), or -1 for current schedule (default).
        """
        _check_range(baseline_a, "baseline_a")
        _check_range(baseline_b, "baseline_b", allow_current=True)
        app  = get_app()
        proj = get_proj(app)
        for n in {baseline_a, baseline_b} - {-1}:
            if _baselined_count(proj, n) == 0:
                return json.dumps({"error": f"Baseline {n} has not been saved; nothing to compare."})

        tasks, deltas = [], []
        for t in proj.Tasks:
            if t is None or t.Summary:
                continue
            a_start, a_finish = _date_or_none(getattr(t, _attr(baseline_a, "Start"))), _date_or_none(getattr(t, _attr(baseline_a, "Finish")))
            if baseline_b == -1:
                b_start, b_finish = _date_or_none(t.Start), _date_or_none(t.Finish)
            else:
                b_start, b_finish = _date_or_none(getattr(t, _attr(baseline_b, "Start"))), _date_or_none(getattr(t, _attr(baseline_b, "Finish")))
            start_delta = (b_start - a_start).days if a_start and b_start else None
            finish_delta = (b_finish - a_finish).days if a_finish and b_finish else None
            if finish_delta:
                deltas.append(finish_delta)
            tasks.append({"unique_id": t.UniqueID, "name": t.Name,
                          "a_start": _fmt_date(a_start), "a_finish": _fmt_date(a_finish),
                          "b_start": _fmt_date(b_start), "b_finish": _fmt_date(b_finish),
                          "start_delta": start_delta, "finish_delta": finish_delta,
                          "in_baseline": a_start is not None})

        tasks.sort(key=lambda x: x["finish_delta"] or 0, reverse=True)
        return json.dumps({
            "baseline_a": baseline_a,
            "baseline_b": baseline_b if baseline_b >= 0 else "current",
            "summary": {
                "total_tasks":         len(tasks),
                "tasks_not_baselined": sum(not x["in_baseline"] for x in tasks),
                "tasks_with_variance": len(deltas),
                "avg_finish_variance": round(sum(deltas) / len(deltas), 1) if deltas else 0,
                "max_slippage":        max([0] + deltas),
            },
            "tasks": tasks,
        }, indent=2)

    @mcp.tool()
    def get_variance_report(baseline: int = 0) -> str:
        """
        Schedule (working days) and cost variance per task compared to a baseline.
        Returns an error if the baseline has never been saved.

        Args:
            baseline: Baseline number (0-10). Default 0.
        """
        _check_range(baseline, "baseline")
        app  = get_app()
        proj = get_proj(app)
        mpd  = _get_mpd(proj)
        if _baselined_count(proj, baseline) == 0:
            return json.dumps({"error": f"Baseline {baseline} has not been saved; no variance to report."})

        def working_days(a, b):
            a, b = (d.replace(tzinfo=datetime.timezone.utc) for d in (a, b))  # keep wall-clock (see com_write)
            return round(app.DateDifference(a, b) / mpd, 2) if a <= b else -round(app.DateDifference(b, a) / mpd, 2)

        tasks = []
        for t in proj.Tasks:
            if t is None or t.Summary:
                continue
            bl_start, bl_finish = getattr(t, _attr(baseline, "Start")), getattr(t, _attr(baseline, "Finish"))
            if not _date_or_none(bl_start):
                continue
            bl_cost = getattr(t, _attr(baseline, "Cost")) or 0
            tasks.append({
                "unique_id":            t.UniqueID,
                "name":                 t.Name,
                "start":                _fmt_date(t.Start),
                "finish":               _fmt_date(t.Finish),
                "baseline_start":       _fmt_date(bl_start),
                "baseline_finish":      _fmt_date(bl_finish),
                "start_variance_days":  working_days(_to_naive(bl_start), _to_naive(t.Start)),
                "finish_variance_days": working_days(_to_naive(bl_finish), _to_naive(t.Finish)),
                "cost":                 round(t.Cost or 0, 2),
                "baseline_cost":        round(bl_cost, 2),
                "cost_variance":        round((t.Cost or 0) - bl_cost, 2),
            })
        with_variance = [x for x in tasks if x["start_variance_days"] or x["finish_variance_days"] or x["cost_variance"]]
        return json.dumps({"baseline": baseline, "total_tasks": len(tasks), "with_variance": len(with_variance),
                           "tasks": with_variance}, indent=2)
