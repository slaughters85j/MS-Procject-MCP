"""
Critical path sequencing, period-bounded critical tasks, and delay what-if analysis.
"""

import datetime
import json

from ..com_helpers import (
    get_app, get_proj, _get_mpd, _parse_date, _fmt_date, _to_naive, _find_task,
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


    @mcp.tool()
    def what_if_delay(
        unique_id: int,
        delay_days: int = 5,
    ) -> str:
        """
        What-if analysis: 'If I delay task X by N days, what happens to the schedule?'
        Simulates the delay WITHOUT modifying the project — read-only analysis.

        Shows:
        - Whether the project end date would change (and by how much)
        - Which tasks would become newly critical
        - Which tasks would lose their slack
        - Downstream tasks affected

        Args:
            unique_id:  Task UniqueID to simulate delaying.
            delay_days: Number of working days to simulate (default 5).
        """
        app  = get_app()
        proj = get_proj(app)
        mpd  = _get_mpd(proj)

        target = _find_task(proj, unique_id)
        if target is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})

        if target.Summary:
            return json.dumps({"error": "Cannot simulate delay on a summary task. Choose a work task or milestone."})

        delay_minutes = delay_days * mpd

        # Gather current state of all tasks
        task_data = {}
        for t in proj.Tasks:
            if t is None or t.Summary:
                continue
            try:
                ts = t.TotalSlack if t.TotalSlack is not None else 0
                fs = t.FreeSlack if t.FreeSlack is not None else 0
            except Exception:
                ts = 0
                fs = 0

            task_data[t.UniqueID] = {
                "name":         t.Name,
                "start":        _to_naive(t.Start),
                "finish":       _to_naive(t.Finish),
                "total_slack":  ts,
                "free_slack":   fs,
                "critical":     bool(t.Critical),
                "milestone":    bool(t.Milestone),
                "duration":     t.Duration or 0,
            }

        target_info = task_data[unique_id]
        target_total_slack = target_info["total_slack"]
        target_free_slack  = target_info["free_slack"]

        # Project end date impact
        project_finish = _to_naive(proj.ProjectFinish)
        slack_days = round(target_total_slack / mpd, 2)
        excess_delay = delay_days - slack_days  # days beyond available slack

        project_delay_days = max(0, round(excess_delay, 2)) if excess_delay > 0 else 0

        new_project_finish = None
        if project_delay_days > 0 and project_finish:
            new_project_finish = _fmt_date(project_finish + datetime.timedelta(days=int(project_delay_days * 1.4)))  # rough calendar conversion

        # Walk downstream tasks (successors chain)
        downstream_affected = []
        newly_critical = []
        slack_consumed = []
        visited = set()

        def walk_successors(uid, accumulated_delay_min):
            if uid in visited:
                return
            visited.add(uid)

            t_info = task_data.get(uid)
            if not t_info:
                return

            for t in proj.Tasks:
                if t is None or t.UniqueID != uid:
                    continue
                try:
                    for dep in t.TaskDependencies:
                        if dep.From.UniqueID == uid:
                            succ_uid = dep.To.UniqueID
                            succ_info = task_data.get(succ_uid)
                            if succ_info and succ_uid not in visited:
                                succ_free_slack = succ_info["free_slack"]
                                succ_total_slack = succ_info["total_slack"]
                                effective_delay = max(0, accumulated_delay_min - succ_free_slack)

                                entry = {
                                    "unique_id":         succ_uid,
                                    "name":              succ_info["name"],
                                    "current_start":     _fmt_date(succ_info["start"]),
                                    "current_finish":    _fmt_date(succ_info["finish"]),
                                    "current_slack_days": round(succ_total_slack / mpd, 2),
                                    "remaining_slack_days": round(max(0, succ_total_slack - accumulated_delay_min) / mpd, 2),
                                    "would_shift_days":  round(effective_delay / mpd, 2),
                                    "milestone":         succ_info["milestone"],
                                }

                                downstream_affected.append(entry)

                                # Check if task becomes newly critical
                                if not succ_info["critical"] and accumulated_delay_min >= succ_total_slack:
                                    newly_critical.append({
                                        "unique_id": succ_uid,
                                        "name":      succ_info["name"],
                                        "was_slack_days": round(succ_total_slack / mpd, 2),
                                    })

                                # Check if slack is significantly consumed
                                if succ_total_slack > 0 and accumulated_delay_min > 0:
                                    pct_consumed = min(100, round(accumulated_delay_min / succ_total_slack * 100))
                                    if pct_consumed >= 50:
                                        slack_consumed.append({
                                            "unique_id":      succ_uid,
                                            "name":           succ_info["name"],
                                            "original_slack_days": round(succ_total_slack / mpd, 2),
                                            "percent_consumed":    pct_consumed,
                                        })

                                walk_successors(succ_uid, effective_delay)
                except Exception:
                    pass
                break

        walk_successors(unique_id, delay_minutes)

        # Build severity assessment
        if project_delay_days > 0:
            severity = "HIGH"
            summary = f"Project end date would slip by ~{project_delay_days} days. {len(newly_critical)} task(s) become newly critical."
        elif len(newly_critical) > 0:
            severity = "MEDIUM"
            summary = f"No project delay, but {len(newly_critical)} task(s) would become critical (slack fully consumed)."
        elif len(slack_consumed) > 0:
            severity = "LOW"
            summary = f"No project delay, but slack reduced on {len(slack_consumed)} downstream task(s)."
        else:
            severity = "NONE"
            summary = f"Task has {slack_days} days of slack. A {delay_days}-day delay is fully absorbed."

        return json.dumps({
            "task":               {"unique_id": unique_id, "name": target_info["name"]},
            "simulated_delay_days": delay_days,
            "severity":           severity,
            "summary":            summary,
            "current_slack_days": slack_days,
            "project_impact": {
                "current_finish":     _fmt_date(project_finish),
                "estimated_new_finish": new_project_finish,
                "delay_days":         project_delay_days,
            },
            "downstream_affected":   len(downstream_affected),
            "newly_critical_count":  len(newly_critical),
            "newly_critical":        newly_critical,
            "slack_consumed":        slack_consumed,
            "downstream_tasks":      downstream_affected,
        }, indent=2)
