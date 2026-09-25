"""
Delay what-if analysis: the downstream and project-finish impact of a hypothetical task delay,
computed from the current schedule without changing it.
"""

import json

from ..com_helpers import (
    get_app, get_proj, _get_mpd, _fmt_date, _to_naive, _find_task,
)


def register_what_if_tools(mcp):
    """Register the what-if analysis tools on the FastMCP instance."""

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

        # Project end date impact
        project_finish = _to_naive(proj.ProjectFinish)
        slack_days = round(target_total_slack / mpd, 2)
        excess_delay = delay_days - slack_days  # days beyond available slack

        project_delay_days = max(0, round(excess_delay, 2)) if excess_delay > 0 else 0

        new_project_finish = None
        if project_delay_days > 0 and project_finish:
            # Working-time arithmetic on the project calendar (weekends, holidays), not calendar days.
            new_project_finish = _fmt_date(app.DateAdd(proj.ProjectFinish, round(project_delay_days * mpd)))

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
