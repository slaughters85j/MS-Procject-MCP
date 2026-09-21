"""
Schedule health: critical path list, analysis, validation, milestones, and available slack.
"""

import datetime
import json

from ..com_helpers import get_app, get_proj, _get_mpd, task_to_dict, _fmt_date, _to_naive


def register_schedule_analysis_tools(mcp):
    """Register the schedule analysis tools on the FastMCP instance."""

    @mcp.tool()
    def get_critical_path() -> str:
        """Return all tasks on the critical path (non-summary)."""
        app  = get_app()
        proj = get_proj(app)

        results = []
        for t in proj.Tasks:
            if t is not None and t.Critical and not t.Summary:
                results.append(task_to_dict(t, proj))

        return json.dumps({"count": len(results), "tasks": results}, indent=2)


    @mcp.tool()
    def get_schedule_analysis() -> str:
        """
        Return float/slack metrics and schedule health for all non-summary tasks.
        TotalSlack and FreeSlack are converted from minutes to working days.
        """
        app  = get_app()
        proj = get_proj(app)
        mpd  = _get_mpd(proj)

        def fmt(dt):
            try:
                return str(dt)[:10] if dt else None
            except Exception:
                return None

        tasks = []
        zero_float = 0
        negative_float = 0
        total_slack_sum = 0
        count = 0

        for t in proj.Tasks:
            if t is None or t.Summary:
                continue
            count += 1

            try:
                ts = round(t.TotalSlack / mpd, 2) if t.TotalSlack is not None else 0
            except Exception:
                ts = 0
            try:
                fs = round(t.FreeSlack / mpd, 2) if t.FreeSlack is not None else 0
            except Exception:
                fs = 0

            if ts == 0:
                zero_float += 1
            if ts < 0:
                negative_float += 1
            total_slack_sum += ts

            tasks.append({
                "unique_id":       t.UniqueID,
                "name":            t.Name,
                "total_slack_days": ts,
                "free_slack_days":  fs,
                "critical":        bool(t.Critical),
                "start":           fmt(t.Start),
                "finish":          fmt(t.Finish),
            })

        return json.dumps({
            "summary": {
                "total_tasks":     count,
                "zero_float":      zero_float,
                "negative_float":  negative_float,
                "avg_total_slack":  round(total_slack_sum / count, 2) if count else 0,
            },
            "tasks": tasks,
        }, indent=2)


    @mcp.tool()
    def validate_schedule() -> str:
        """
        Comprehensive schedule health check — the PMO's best friend.
        Checks for orphan tasks, missing resources, past-due zero-progress,
        empty summaries, missing dates, and negative slack.
        Returns a health score (0-100) and categorized issues.
        """
        app   = get_app()
        proj  = get_proj(app)
        mpd   = _get_mpd(proj)
        today = datetime.datetime.now()

        issues = {
            "orphan_tasks":       {"count": 0, "tasks": []},
            "no_resources":       {"count": 0, "tasks": []},
            "past_due_no_progress": {"count": 0, "tasks": []},
            "empty_summaries":    {"count": 0, "tasks": []},
            "missing_dates":      {"count": 0, "tasks": []},
            "negative_slack":     {"count": 0, "tasks": []},
        }

        total_tasks = 0
        tasks_list  = []  # (task, is_summary, outline_level)

        for t in proj.Tasks:
            if t is None:
                continue
            total_tasks += 1
            tasks_list.append(t)

        for i, t in enumerate(tasks_list):
            tid = {"unique_id": t.UniqueID, "name": t.Name}

            # Empty summaries: summary with no children
            if t.Summary:
                has_child = False
                if i + 1 < len(tasks_list):
                    next_t = tasks_list[i + 1]
                    if next_t.OutlineLevel > t.OutlineLevel:
                        has_child = True
                if not has_child:
                    issues["empty_summaries"]["count"] += 1
                    issues["empty_summaries"]["tasks"].append(tid)
                continue  # Skip non-leaf checks for summaries

            # Orphan tasks: no predecessors AND no successors
            preds = (t.Predecessors or "").strip()
            # Check if this task is a predecessor for any other task
            has_successor = False
            task_id_str = str(t.ID)
            for other in tasks_list:
                if other is None or other.UniqueID == t.UniqueID:
                    continue
                other_preds = (other.Predecessors or "").strip()
                if other_preds:
                    # Check if our task ID appears in other's predecessors
                    for part in other_preds.split(","):
                        part = part.strip()
                        # Extract the numeric ID from predecessor string like "5FS" or "5"
                        num = ""
                        for ch in part:
                            if ch.isdigit():
                                num += ch
                            else:
                                break
                        if num == task_id_str:
                            has_successor = True
                            break
                if has_successor:
                    break

            if not preds and not has_successor:
                issues["orphan_tasks"]["count"] += 1
                issues["orphan_tasks"]["tasks"].append(tid)

            # No resources (non-milestone)
            if not t.Milestone and not (t.ResourceNames or "").strip():
                issues["no_resources"]["count"] += 1
                issues["no_resources"]["tasks"].append(tid)

            # Past due, zero progress
            try:
                fin = _to_naive(t.Finish)
                if fin and fin < today and t.PercentComplete == 0:
                    issues["past_due_no_progress"]["count"] += 1
                    issues["past_due_no_progress"]["tasks"].append(tid)
            except Exception:
                pass

            # Missing dates
            try:
                if not t.Start or not t.Finish:
                    issues["missing_dates"]["count"] += 1
                    issues["missing_dates"]["tasks"].append(tid)
            except Exception:
                pass

            # Negative slack
            try:
                if t.TotalSlack is not None and t.TotalSlack < 0:
                    issues["negative_slack"]["count"] += 1
                    issues["negative_slack"]["tasks"].append(tid)
            except Exception:
                pass

        total_issues = sum(cat["count"] for cat in issues.values())
        health_score = max(0, round(100 - (total_issues / total_tasks * 100))) if total_tasks else 0

        return json.dumps({
            "project":      proj.Name,
            "health_score": health_score,
            "issues":       issues,
            "summary": {
                "total_tasks":  total_tasks,
                "total_issues": total_issues,
            },
        }, indent=2)


    @mcp.tool()
    def get_milestone_report(days_ahead: int = 30, upcoming_count: int = 10) -> str:
        """
        Milestone-focused status report for executive dashboards.
        Categorizes milestones as complete, overdue, at_risk, or on_track.
        Includes baseline variance if a baseline is saved.

        Args:
            days_ahead:     Number of days ahead to consider 'at risk' (default 30).
            upcoming_count: Max upcoming milestones to return (default 10).
        """
        app   = get_app()
        proj  = get_proj(app)
        today = datetime.datetime.now()
        horizon = today + datetime.timedelta(days=days_ahead)

        by_status = {"complete": 0, "overdue": 0, "at_risk": 0, "on_track": 0}
        upcoming  = []
        overdue   = []
        total     = 0

        for t in proj.Tasks:
            if t is None or not t.Milestone:
                continue
            total += 1

            finish = None
            try:
                finish = _to_naive(t.Finish)
            except Exception:
                pass

            pct = t.PercentComplete

            # Baseline variance
            variance_days = None
            try:
                bf = _to_naive(t.BaselineFinish)
                if bf and finish:
                    delta = finish - bf
                    variance_days = delta.days if hasattr(delta, "days") else None
            except Exception:
                pass

            entry = {
                "unique_id":      t.UniqueID,
                "name":           t.Name,
                "finish":         _fmt_date(finish),
                "percent":        pct,
                "variance_days":  variance_days,
            }

            if pct >= 100:
                by_status["complete"] += 1
            elif finish and finish < today:
                by_status["overdue"] += 1
                overdue.append(entry)
            elif finish and finish <= horizon and pct < 100:
                by_status["at_risk"] += 1
                upcoming.append(entry)
            else:
                by_status["on_track"] += 1
                if finish:
                    upcoming.append(entry)

        # Sort upcoming by finish asc, overdue by finish asc
        upcoming.sort(key=lambda x: x["finish"] or "")
        overdue.sort(key=lambda x: x["finish"] or "")

        return json.dumps({
            "total_milestones": total,
            "by_status":        by_status,
            "upcoming":         upcoming[:upcoming_count],
            "overdue":          overdue,
        }, indent=2)


    @mcp.tool()
    def find_available_slack(min_days: int = 5) -> str:
        """
        Find tasks with positive float — where can we absorb delay?

        Args:
            min_days: Minimum total slack in working days (default 5).
        """
        app  = get_app()
        proj = get_proj(app)
        mpd  = _get_mpd(proj)

        tasks = []
        for t in proj.Tasks:
            if t is None or t.Summary:
                continue

            try:
                ts = t.TotalSlack
                if ts is None:
                    continue
                ts_days = round(ts / mpd, 2)
                if ts_days < min_days:
                    continue

                fs = 0
                try:
                    fs = round(t.FreeSlack / mpd, 2) if t.FreeSlack else 0
                except Exception:
                    pass

                tasks.append({
                    "unique_id":        t.UniqueID,
                    "name":             t.Name,
                    "total_slack_days": ts_days,
                    "free_slack_days":  fs,
                    "start":            _fmt_date(t.Start),
                    "finish":           _fmt_date(t.Finish),
                    "resource_names":   t.ResourceNames or "",
                })
            except Exception:
                continue

        tasks.sort(key=lambda x: x["total_slack_days"], reverse=True)

        return json.dumps({
            "min_days": min_days,
            "count":    len(tasks),
            "tasks":    tasks,
        }, indent=2)
