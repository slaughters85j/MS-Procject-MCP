"""
Progress reporting: summary, WBS roll-up, WBS structure, and actual work.
"""

import json

from ..com_helpers import get_app, get_proj, _get_mpd, _fmt_date, _to_naive, is_overdue
from ..guards import format_response, _RESPONSE_MGMT


def register_progress_tools(mcp):
    """Register the progress tools on the FastMCP instance."""

    @mcp.tool()
    def get_progress_summary() -> str:
        """
        Return a high-level progress summary:
        - Count by % complete bucket (0%, 1-99%, 100%)
        - Count by RAG status (Text1)
        - Count of overdue, critical tasks
        """
        import datetime
        today = datetime.datetime.now()
        app   = get_app()
        proj  = get_proj(app)

        not_started = in_progress = complete = 0
        rag_counts  = {"Red": 0, "Amber": 0, "Green": 0, "Other": 0}
        overdue     = critical = 0

        for t in proj.Tasks:
            if t is None or t.Summary:
                continue

            pct = t.PercentComplete
            if pct == 0:
                not_started += 1
            elif pct < 100:
                in_progress += 1
            else:
                complete += 1

            rag = (t.Text1 or "").strip()
            if rag in rag_counts:
                rag_counts[rag] += 1
            elif rag:
                rag_counts["Other"] += 1

            if t.Critical:
                critical += 1

            if is_overdue(t, today):
                overdue += 1

        total = not_started + in_progress + complete

        return json.dumps({
            "project":     proj.Name,
            "total_tasks": total,
            "by_progress": {
                "not_started": not_started,
                "in_progress": in_progress,
                "complete":    complete,
                "pct_complete": round(complete / total * 100, 1) if total else 0,
            },
            "by_rag": rag_counts,
            "overdue":   overdue,
            "critical":  critical,
        }, indent=2)


    @mcp.tool()
    def get_progress_by_wbs(max_level: int = 2) -> str:
        """
        Rolled-up % complete per WBS branch — the PMO dashboard.
        Returns summary tasks at or below max_level with their percent complete.

        Args:
            max_level: Maximum outline level to report (default 2).
        """
        app  = get_app()
        proj = get_proj(app)

        branches = []
        tasks_list = [t for t in proj.Tasks if t is not None]

        for i, t in enumerate(tasks_list):
            if not t.Summary:
                continue
            if t.OutlineLevel > max_level:
                continue

            # Count children
            child_count = 0
            milestones_complete = 0
            milestones_total = 0
            for j in range(i + 1, len(tasks_list)):
                child = tasks_list[j]
                if child.OutlineLevel <= t.OutlineLevel:
                    break
                if not child.Summary:
                    child_count += 1
                    if child.Milestone:
                        milestones_total += 1
                        if child.PercentComplete >= 100:
                            milestones_complete += 1

            branches.append({
                "unique_id":          t.UniqueID,
                "name":               t.Name,
                "level":              t.OutlineLevel,
                "percent_complete":   t.PercentComplete,
                "start":              _fmt_date(t.Start),
                "finish":             _fmt_date(t.Finish),
                "child_count":        child_count,
                "milestones_complete": milestones_complete,
                "milestones_total":   milestones_total,
            })

        return json.dumps({
            "max_level": max_level,
            "branches":  branches,
        }, indent=2)


    @mcp.tool()
    def get_wbs_structure(max_level: int = 0) -> str:
        """
        Export the full WBS hierarchy as a nested JSON tree.
        Useful for dashboards, reporting, and verifying project structure.

        Args:
            max_level: Maximum outline level to include (0 = all levels).
        """
        app  = get_app()
        proj = get_proj(app)
        mpd  = _get_mpd(proj)

        def fmt(dt):
            try:
                return str(dt)[:10] if dt else None
            except Exception:
                return None

        # Build flat list first
        flat = []
        for t in proj.Tasks:
            if t is None:
                continue
            if max_level > 0 and t.OutlineLevel > max_level:
                continue
            flat.append({
                "unique_id":     t.UniqueID,
                "id":            t.ID,
                "name":          t.Name,
                "level":         t.OutlineLevel,
                "summary":       bool(t.Summary),
                "milestone":     bool(t.Milestone),
                "start":         fmt(t.Start),
                "finish":        fmt(t.Finish),
                "duration_days": round(t.Duration / mpd, 2) if t.Duration else 0,
                "children":      [],
            })

        # Build tree using stack
        root = {"name": proj.Name, "level": 0, "children": []}
        stack = [root]

        for node in flat:
            level = node["level"]
            # Pop stack back to parent level
            while len(stack) > level:
                stack.pop()
            # Append to current parent
            stack[-1]["children"].append(node)
            # Push this node as potential parent
            stack.append(node)

        if _RESPONSE_MGMT:
            return format_response(root)
        return json.dumps(root, indent=2)


    @mcp.tool()
    def get_actual_work() -> str:
        """
        Return actual vs remaining work per task and project totals.
        Work values are converted from COM minutes to hours.
        """
        app  = get_app()
        proj = get_proj(app)

        tasks = []
        total_work = 0.0
        total_actual = 0.0
        total_remaining = 0.0

        for t in proj.Tasks:
            if t is None or t.Summary:
                continue
            try:
                w = (t.Work or 0) / 60.0
                a = (t.ActualWork or 0) / 60.0
                r = (t.RemainingWork or 0) / 60.0
                total_work += w
                total_actual += a
                total_remaining += r
                tasks.append({
                    "unique_id":      t.UniqueID,
                    "name":           t.Name,
                    "work_hours":     round(w, 2),
                    "actual_hours":   round(a, 2),
                    "remaining_hours": round(r, 2),
                    "pct_work_complete": t.PercentWorkComplete,
                })
            except Exception:
                continue

        pct = round(total_actual / total_work * 100, 1) if total_work else 0.0

        return json.dumps({
            "totals": {
                "work_hours":        round(total_work, 2),
                "actual_hours":      round(total_actual, 2),
                "remaining_hours":   round(total_remaining, 2),
                "pct_work_complete": pct,
            },
            "count": len(tasks),
            "tasks": tasks,
        }, indent=2)
