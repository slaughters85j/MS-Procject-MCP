"""
Predecessor links: add, remove, inspect, and trace dependency chains.
"""

import json

from ..com_helpers import get_app, get_proj, _get_mpd, _fmt_date, _find_task
from ..guards import format_response, _RESPONSE_MGMT


def register_dependencies_tools(mcp):
    """Register the dependencies tools on the FastMCP instance."""

    @mcp.tool()
    def add_predecessor(
        successor_unique_id:   int,
        predecessor_unique_id: int,
        link_type:             str = "FS",
        lag_days:              int = 0,
    ) -> str:
        """
        Add a predecessor link between two tasks.

        Args:
            successor_unique_id:   The task that depends on the predecessor.
            predecessor_unique_id: The task that must finish/start first.
            link_type:             'FS' (default), 'SS', 'FF', or 'SF'.
            lag_days:              Lag in days (positive = lag, negative = lead).
        """
        app  = get_app()
        proj = get_proj(app)

        uid_to_id = {t.UniqueID: t.ID for t in proj.Tasks if t is not None}

        if successor_unique_id not in uid_to_id:
            return json.dumps({"error": f"Successor UniqueID {successor_unique_id} not found."})
        if predecessor_unique_id not in uid_to_id:
            return json.dumps({"error": f"Predecessor UniqueID {predecessor_unique_id} not found."})

        pred_id = uid_to_id[predecessor_unique_id]
        succ_task = None
        for t in proj.Tasks:
            if t is not None and t.UniqueID == successor_unique_id:
                succ_task = t
                break

        lag_str = ""
        if lag_days > 0:
            lag_str = f"+{lag_days}d"
        elif lag_days < 0:
            lag_str = f"{lag_days}d"

        existing = succ_task.Predecessors.strip()
        new_pred  = f"{pred_id}{link_type}{lag_str}"

        if existing:
            succ_task.Predecessors = existing + "," + new_pred
        else:
            succ_task.Predecessors = new_pred

        app.FileSave()
        return json.dumps({
            "status":       "linked",
            "successor":    successor_unique_id,
            "predecessor":  predecessor_unique_id,
            "link":         new_pred,
            "predecessors": succ_task.Predecessors,
        }, indent=2)


    @mcp.tool()
    def bulk_add_predecessors(links_json: str) -> str:
        """
        Add multiple predecessor links in one call.

        Args:
            links_json: JSON string — list of link objects:
                [{successor_unique_id, predecessor_unique_id, link_type (default "FS"), lag_days (default 0)}]
                Example: '[{"successor_unique_id": 10, "predecessor_unique_id": 5, "link_type": "FS"}]'
        """
        links = json.loads(links_json)
        app   = get_app()
        proj  = get_proj(app)

        uid_to_id = {t.UniqueID: t.ID for t in proj.Tasks if t is not None}
        uid_to_task = {t.UniqueID: t for t in proj.Tasks if t is not None}

        linked = 0
        errors = []

        for link in links:
            succ_uid = link["successor_unique_id"]
            pred_uid = link["predecessor_unique_id"]
            lt       = link.get("link_type", "FS")
            lag      = link.get("lag_days", 0)

            if succ_uid not in uid_to_id:
                errors.append({"successor_unique_id": succ_uid, "error": "not found"})
                continue
            if pred_uid not in uid_to_id:
                errors.append({"predecessor_unique_id": pred_uid, "error": "not found"})
                continue

            pred_id   = uid_to_id[pred_uid]
            succ_task = uid_to_task[succ_uid]

            lag_str = ""
            if lag > 0:
                lag_str = f"+{lag}d"
            elif lag < 0:
                lag_str = f"{lag}d"

            new_pred = f"{pred_id}{lt}{lag_str}"
            existing = succ_task.Predecessors.strip()

            if existing:
                succ_task.Predecessors = existing + "," + new_pred
            else:
                succ_task.Predecessors = new_pred

            linked += 1

        app.FileSave()
        return json.dumps({
            "linked": linked,
            "errors": errors,
        }, indent=2)


    @mcp.tool()
    def remove_predecessor(
        successor_unique_id:   int,
        predecessor_unique_id: int,
    ) -> str:
        """Remove a specific predecessor link from a task."""
        app  = get_app()
        proj = get_proj(app)

        uid_to_id = {t.UniqueID: t.ID for t in proj.Tasks if t is not None}

        if successor_unique_id not in uid_to_id:
            return json.dumps({"error": f"Successor UniqueID {successor_unique_id} not found."})

        pred_id   = uid_to_id.get(predecessor_unique_id)
        succ_task = None
        for t in proj.Tasks:
            if t is not None and t.UniqueID == successor_unique_id:
                succ_task = t
                break

        existing = succ_task.Predecessors.strip()
        if not existing:
            return json.dumps({"status": "no_change", "message": "Task has no predecessors."})

        parts     = [p.strip() for p in existing.split(",")]
        filtered  = [p for p in parts if not p.startswith(str(pred_id))]
        succ_task.Predecessors = ",".join(filtered)

        app.FileSave()
        return json.dumps({
            "status":              "unlinked",
            "successor":           successor_unique_id,
            "removed_predecessor": predecessor_unique_id,
            "predecessors_now":    succ_task.Predecessors,
        }, indent=2)


    @mcp.tool()
    def get_task_dependencies(unique_id: int) -> str:
        """Get all predecessor and successor dependencies for a task."""
        app  = get_app()
        proj = get_proj(app)
        mpd  = _get_mpd(proj)

        target = None
        for t in proj.Tasks:
            if t is not None and t.UniqueID == unique_id:
                target = t
                break

        if target is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})

        preds = []
        try:
            for dep in target.TaskDependencies:
                if dep.To.UniqueID == unique_id:
                    preds.append({
                        "unique_id": dep.From.UniqueID,
                        "name":      dep.From.Name,
                        "type":      dep.Type,
                        "lag_days":  round(dep.Lag / mpd, 2),
                    })
        except Exception:
            pass

        succs = []
        try:
            for dep in target.TaskDependencies:
                if dep.From.UniqueID == unique_id:
                    succs.append({
                        "unique_id": dep.To.UniqueID,
                        "name":      dep.To.Name,
                        "type":      dep.Type,
                        "lag_days":  round(dep.Lag / mpd, 2),
                    })
        except Exception:
            pass

        result = {
            "task":        {"unique_id": unique_id, "name": target.Name},
            "predecessors": preds,
            "successors":   succs,
        }
        if _RESPONSE_MGMT:
            return format_response(result)
        return json.dumps(result, indent=2)


    @mcp.tool()
    def get_dependency_chain(unique_id: int, direction: str = "successors", max_depth: int = 50) -> str:
        """
        Recursive walk of the dependency chain — 'what's downstream if this slips?'

        Args:
            unique_id: Starting task UniqueID (required).
            direction: 'successors' (default) or 'predecessors'.
            max_depth: Maximum depth to walk (default 50, safety cap).
        """
        app  = get_app()
        proj = get_proj(app)

        root = _find_task(proj, unique_id)
        if root is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})

        visited = set()
        chain = []
        queue = [(root, 0)]  # (task, depth)
        visited.add(root.UniqueID)

        while queue:
            current, depth = queue.pop(0)
            if depth > 0:
                chain.append({
                    "unique_id": current.UniqueID,
                    "name":      current.Name,
                    "depth":     depth,
                    "start":     _fmt_date(current.Start),
                    "finish":    _fmt_date(current.Finish),
                    "critical":  bool(current.Critical),
                })
            if depth >= max_depth:
                continue

            try:
                for dep in current.TaskDependencies:
                    if direction.lower() == "successors":
                        if dep.From.UniqueID == current.UniqueID:
                            next_task = dep.To
                        else:
                            continue
                    else:
                        if dep.To.UniqueID == current.UniqueID:
                            next_task = dep.From
                        else:
                            continue

                    if next_task.UniqueID not in visited:
                        visited.add(next_task.UniqueID)
                        queue.append((next_task, depth + 1))
            except Exception:
                pass

        return json.dumps({
            "root":          {"unique_id": unique_id, "name": root.Name},
            "direction":     direction,
            "depth_reached": max(e["depth"] for e in chain) if chain else 0,
            "chain":         chain,
        }, indent=2)
