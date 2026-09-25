"""
Critical path sequencing and period-bounded critical tasks. (Delay what-if analysis: what_if.py.)
"""

import datetime
import json

from ..com_helpers import (
    get_app, get_proj, _get_mpd, _parse_date, _fmt_date, _to_naive,
)


def register_critical_path_tools(mcp):
    """Register the critical path tools on the FastMCP instance."""

    @mcp.tool()
    def get_critical_path_sequence() -> str:
        """
        Return the critical path as an ordered chain from project start to finish.
        Unlike get_critical_path (flat list), this shows the exact sequence of tasks
        that drives the project end date, connected by their dependency links.

        Returns the longest path through the network with total duration,
        each task's contribution, and the driving relationships.
        """
        app  = get_app()
        proj = get_proj(app)
        mpd  = _get_mpd(proj)

        # Build adjacency graph of critical tasks only
        critical_tasks = {}
        for t in proj.Tasks:
            if t is not None and t.Critical and not t.Summary:
                critical_tasks[t.UniqueID] = t

        if not critical_tasks:
            return json.dumps({"error": "No critical tasks found. Ensure the project has tasks with dependencies."})

        # Build forward adjacency: uid -> [(successor_uid, link_type, lag_days)]
        forward = {uid: [] for uid in critical_tasks}
        incoming = {uid: 0 for uid in critical_tasks}

        LINK_NAMES = {0: "FF", 1: "FS", 2: "SF", 3: "SS"}

        for uid, t in critical_tasks.items():
            try:
                for dep in t.TaskDependencies:
                    if dep.From.UniqueID == uid:
                        succ_uid = dep.To.UniqueID
                        if succ_uid in critical_tasks:
                            lag = round(dep.Lag / mpd, 2) if dep.Lag else 0
                            link = LINK_NAMES.get(dep.Type, "FS")
                            forward[uid].append((succ_uid, link, lag))
                            incoming[succ_uid] = incoming.get(succ_uid, 0) + 1
            except Exception:
                pass

        # Find start nodes (no critical predecessors)
        start_nodes = [uid for uid, count in incoming.items() if count == 0]

        # Find the longest path using DFS (by finish date)
        best_path = []

        def dfs(uid, path):
            nonlocal best_path
            path.append(uid)
            successors = forward.get(uid, [])
            critical_successors = [s for s in successors if s[0] in critical_tasks]

            if not critical_successors:
                # End of chain — check if this is the longest
                if not best_path or len(path) > len(best_path):
                    best_path = list(path)
                else:
                    # Tie-break by finish date of last task
                    last_current = critical_tasks[path[-1]]
                    last_best = critical_tasks[best_path[-1]]
                    try:
                        if _to_naive(last_current.Finish) > _to_naive(last_best.Finish):
                            best_path = list(path)
                    except Exception:
                        if len(path) > len(best_path):
                            best_path = list(path)
            else:
                for succ_uid, _, _ in critical_successors:
                    if succ_uid not in path:  # avoid cycles
                        dfs(succ_uid, path)

            path.pop()

        for start in start_nodes:
            dfs(start, [])

        # If no path found from start nodes, fall back to all critical tasks sorted by start
        if not best_path:
            sorted_critical = sorted(critical_tasks.values(), key=lambda t: _to_naive(t.Start) or datetime.datetime.max)
            best_path = [t.UniqueID for t in sorted_critical]

        # Build the ordered sequence with link info
        sequence = []
        total_duration = 0
        for i, uid in enumerate(best_path):
            t = critical_tasks[uid]
            dur = round(t.Duration / mpd, 2) if t.Duration else 0
            total_duration += dur

            entry = {
                "step":            i + 1,
                "unique_id":       t.UniqueID,
                "name":            t.Name,
                "start":           _fmt_date(t.Start),
                "finish":          _fmt_date(t.Finish),
                "duration_days":   dur,
                "milestone":       bool(t.Milestone),
                "percent_complete": t.PercentComplete,
                "resource_names":  t.ResourceNames or "",
            }

            # Add link info to next task
            if i < len(best_path) - 1:
                next_uid = best_path[i + 1]
                for succ_uid, link, lag in forward.get(uid, []):
                    if succ_uid == next_uid:
                        entry["link_to_next"] = link
                        entry["lag_days"] = lag
                        break

            sequence.append(entry)

        # Project dates
        proj_start = _fmt_date(proj.ProjectStart)
        proj_finish = _fmt_date(proj.ProjectFinish)

        return json.dumps({
            "project_start":       proj_start,
            "project_finish":      proj_finish,
            "critical_path_length": len(sequence),
            "total_duration_days":  total_duration,
            "total_critical_tasks": len(critical_tasks),
            "sequence":            sequence,
        }, indent=2)


    @mcp.tool()
    def get_critical_tasks_for_period(
        start_date: str,
        end_date: str,
        include_milestones: bool = True,
        include_non_critical_milestones: bool = False,
    ) -> str:
        """
        Return critical tasks and key milestones that fall within a date range.
        Perfect for period-focused reporting: 'What's critical in Q2?'

        Args:
            start_date:  Period start (YYYY-MM-DD, required).
            end_date:    Period end (YYYY-MM-DD, required).
            include_milestones: Include critical milestones in results (default True).
            include_non_critical_milestones: Also include non-critical milestones in the period (default False).
        """
        app  = get_app()
        proj = get_proj(app)
        mpd  = _get_mpd(proj)

        period_start = _parse_date(start_date)
        period_end   = _parse_date(end_date)
        if not period_start or not period_end:
            return json.dumps({"error": "Both start_date and end_date are required (YYYY-MM-DD)."})
        period_end = period_end.replace(hour=23, minute=59)  # inclusive of the whole end day

        critical_tasks = []
        critical_milestones = []
        other_milestones = []

        for t in proj.Tasks:
            if t is None or t.Summary:
                continue

            try:
                t_start  = _to_naive(t.Start)
                t_finish = _to_naive(t.Finish)
            except Exception:
                continue

            if not t_start or not t_finish:
                continue

            # Check overlap: task intersects the period
            overlaps = t_start <= period_end and t_finish >= period_start

            if not overlaps:
                continue

            dur = round(t.Duration / mpd, 2) if t.Duration else 0

            # Calculate how much of the task falls within the period
            overlap_start = max(t_start, period_start)
            overlap_end   = min(t_finish, period_end)
            overlap_days  = max(0, (overlap_end - overlap_start).days)

            entry = {
                "unique_id":        t.UniqueID,
                "name":             t.Name,
                "start":            _fmt_date(t_start),
                "finish":           _fmt_date(t_finish),
                "duration_days":    dur,
                "percent_complete": t.PercentComplete,
                "milestone":        bool(t.Milestone),
                "critical":         bool(t.Critical),
                "resource_names":   t.ResourceNames or "",
                "overlap_days":     overlap_days,
            }

            # Baseline variance
            try:
                bf = _to_naive(t.BaselineFinish)
                if bf and t_finish:
                    entry["finish_variance_days"] = (t_finish - bf).days
            except Exception:
                pass

            if t.Critical:
                if t.Milestone and include_milestones:
                    critical_milestones.append(entry)
                elif not t.Milestone:
                    critical_tasks.append(entry)
            elif t.Milestone and include_non_critical_milestones:
                other_milestones.append(entry)

        # Sort by start date
        critical_tasks.sort(key=lambda x: x["start"] or "")
        critical_milestones.sort(key=lambda x: x["finish"] or "")
        other_milestones.sort(key=lambda x: x["finish"] or "")

        return json.dumps({
            "period":              {"start": start_date, "end": end_date},
            "critical_task_count": len(critical_tasks),
            "critical_milestone_count": len(critical_milestones),
            "other_milestone_count": len(other_milestones),
            "critical_tasks":      critical_tasks,
            "critical_milestones": critical_milestones,
            "other_milestones":    other_milestones,
        }, indent=2)
