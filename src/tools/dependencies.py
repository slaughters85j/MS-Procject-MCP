"""
Predecessor links: add, remove, inspect, and trace dependency chains.

Links are created and removed through Task.TaskDependencies (COM objects), never by editing
the Predecessors text, so list-separator locales and ID prefixes ("1" vs "12") cannot corrupt them.
"""

import json

from ..com_helpers import get_app, get_proj, _get_mpd, _fmt_date, _find_task
from ..com_write import commit, batch_calc, LINK_TYPES
from ..guards import format_response, _RESPONSE_MGMT


def _link_spec(proj, succ_uid, pred_uid, link_type, lag_days):
    """Validate one link. Returns (successor, predecessor, type code, lag minutes). Raises ValueError."""
    code = LINK_TYPES.get(str(link_type).upper().strip())
    if code is None:
        raise ValueError(f"Invalid link_type '{link_type}'. Use FS, SS, FF, or SF.")
    if succ_uid == pred_uid:
        raise ValueError("A task cannot be its own predecessor.")
    succ, pred = _find_task(proj, succ_uid), _find_task(proj, pred_uid)
    if succ is None:
        raise ValueError(f"Successor UniqueID {succ_uid} not found.")
    if pred is None:
        raise ValueError(f"Predecessor UniqueID {pred_uid} not found.")
    for dep in succ.TaskDependencies:
        if dep.From.UniqueID == pred_uid:
            raise ValueError(f"UniqueID {pred_uid} is already a predecessor of {succ_uid}; "
                             "remove it first to change the link type or lag.")
    return succ, pred, code, round(float(lag_days) * _get_mpd(proj))


def register_dependencies_tools(mcp):
    """Register the dependencies tools on the FastMCP instance."""

    @mcp.tool()
    def add_predecessor(
        successor_unique_id:   int,
        predecessor_unique_id: int,
        link_type:             str = "FS",
        lag_days:              float = 0,
    ) -> str:
        """
        Add a predecessor link between two tasks.

        Args:
            successor_unique_id:   The task that depends on the predecessor.
            predecessor_unique_id: The task that must finish/start first.
            link_type:             'FS' (default), 'SS', 'FF', or 'SF'.
            lag_days:              Lag in working days (positive = lag, negative = lead).
        """
        app  = get_app()
        proj = get_proj(app)
        succ, pred, code, lag = _link_spec(proj, successor_unique_id, predecessor_unique_id, link_type, lag_days)
        succ.TaskDependencies.Add(From=pred, Type=code, Lag=lag)
        commit(app, proj)
        return json.dumps({
            "status":       "linked",
            "successor":    successor_unique_id,
            "predecessor":  predecessor_unique_id,
            "link_type":    str(link_type).upper(),
            "lag_days":     lag_days,
            "predecessors": succ.Predecessors,
        }, indent=2)

    @mcp.tool()
    def bulk_add_predecessors(links_json: str) -> str:
        """
        Add multiple predecessor links in one call. Each link is validated and added
        independently; failures are reported per item and do not stop the others.

        Args:
            links_json: JSON string — list of link objects:
                [{successor_unique_id, predecessor_unique_id, link_type (default "FS"), lag_days (default 0)}]
                Example: '[{"successor_unique_id": 10, "predecessor_unique_id": 5, "link_type": "FS"}]'
        """
        from ..tool_guardrails import _describe_exception
        links = json.loads(links_json)
        if not isinstance(links, list):
            raise ValueError("links_json must be a JSON array of link objects.")
        app  = get_app()
        proj = get_proj(app)
        linked, errors = 0, []
        with batch_calc(app):
            for i, link in enumerate(links):
                try:
                    if not isinstance(link, dict):
                        raise ValueError("item must be an object.")
                    succ, pred, code, lag = _link_spec(
                        proj, link.get("successor_unique_id"), link.get("predecessor_unique_id"),
                        link.get("link_type", "FS"), link.get("lag_days", 0))
                    succ.TaskDependencies.Add(From=pred, Type=code, Lag=lag)
                    linked += 1
                except Exception as e:
                    errors.append({"index": i, "link": link, "error": _describe_exception(e)[0]})
        commit(app, proj)
        return json.dumps({"linked": linked, "errors": errors}, indent=2)

    @mcp.tool()
    def remove_predecessor(
        successor_unique_id:   int,
        predecessor_unique_id: int,
    ) -> str:
        """Remove the one predecessor link from predecessor_unique_id to successor_unique_id."""
        app  = get_app()
        proj = get_proj(app)
        succ = _find_task(proj, successor_unique_id)
        if succ is None:
            return json.dumps({"error": f"Successor UniqueID {successor_unique_id} not found."})
        match = next((d for d in succ.TaskDependencies if d.From.UniqueID == predecessor_unique_id), None)
        if match is None:
            return json.dumps({"error": f"UniqueID {predecessor_unique_id} is not a predecessor of "
                                        f"{successor_unique_id}. Current: {succ.Predecessors or '(none)'}"})
        match.Delete()
        commit(app, proj)
        return json.dumps({
            "status":              "unlinked",
            "successor":           successor_unique_id,
            "removed_predecessor": predecessor_unique_id,
            "predecessors_now":    succ.Predecessors,
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
