"""
Milestone status report: complete, overdue, at-risk and on-track milestones, and the upcoming ones.
"""

import datetime
import json

from ..com_helpers import get_app, get_proj, _fmt_date, _to_naive


def register_milestone_tools(mcp):
    """Register the milestone report tool on the FastMCP instance."""

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
