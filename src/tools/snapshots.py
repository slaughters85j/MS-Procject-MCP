"""
JSON snapshots of a project and diffs between two snapshots.
"""

import json

from ..com_helpers import get_app, get_proj, task_to_dict, _fmt_date
from ..guards import validate_safe_path


def register_snapshots_tools(mcp):
    """Register the snapshots tools on the FastMCP instance."""

    @mcp.tool()
    def snapshot_to_json(output_path: str, include_resources: bool = True) -> str:
        """
        Full project state dump for version control / diff.
        Exports all tasks and optionally resources to a JSON file.

        Args:
            output_path:       Full path for the output JSON file (required).
            include_resources: Include resource data (default True).
        """
        output_path = validate_safe_path(output_path)
        app  = get_app()
        proj = get_proj(app)

        tasks = []
        for t in proj.Tasks:
            if t is not None:
                tasks.append(task_to_dict(t, proj))

        resources = []
        if include_resources:
            try:
                for r in proj.Resources:
                    if r is not None:
                        resources.append({
                            "unique_id":  r.UniqueID,
                            "id":         r.ID,
                            "name":       r.Name,
                            "initials":   r.Initials,
                            "type":       r.Type,
                            "max_units":  r.MaxUnits,
                            "cost":       r.StandardRate,
                            "task_count": r.Assignments.Count,
                        })
            except Exception:
                pass

        project_meta = {
            "name":   proj.Name,
            "start":  _fmt_date(proj.ProjectStart),
            "finish": _fmt_date(proj.ProjectFinish),
        }
        try:
            project_meta["title"]   = proj.Title or ""
            project_meta["manager"] = proj.Manager or ""
        except Exception:
            pass

        snapshot = {
            "project":   project_meta,
            "tasks":     tasks,
            "resources": resources,
        }

        with open(output_path, "w", encoding="utf-8") as fp:
            json.dump(snapshot, fp, indent=2, default=str)

        return json.dumps({
            "status":    "exported",
            "path":      output_path,
            "tasks":     len(tasks),
            "resources": len(resources),
            "project":   project_meta["name"],
        }, indent=2)


    @mcp.tool()
    def snapshot_diff(path_a: str, path_b: str) -> str:
        """
        Compare two JSON snapshot files (from snapshot_to_json) and return
        additions, deletions, and changes.

        Args:
            path_a: Path to the earlier snapshot JSON.
            path_b: Path to the later snapshot JSON.
        """
        import os

        path_a = validate_safe_path(path_a)
        path_b = validate_safe_path(path_b)
        for p in (path_a, path_b):
            if not os.path.exists(p):
                return json.dumps({"error": f"File not found: {p}"})

        with open(path_a, "r", encoding="utf-8") as f:
            snap_a = json.load(f)
        with open(path_b, "r", encoding="utf-8") as f:
            snap_b = json.load(f)

        tasks_a = {t["unique_id"]: t for t in snap_a.get("tasks", [])}
        tasks_b = {t["unique_id"]: t for t in snap_b.get("tasks", [])}

        ids_a = set(tasks_a.keys())
        ids_b = set(tasks_b.keys())

        added   = [tasks_b[uid] for uid in sorted(ids_b - ids_a)]
        deleted = [tasks_a[uid] for uid in sorted(ids_a - ids_b)]

        changed = []
        for uid in sorted(ids_a & ids_b):
            a, b = tasks_a[uid], tasks_b[uid]
            diffs = {}
            for key in set(list(a.keys()) + list(b.keys())):
                va, vb = a.get(key), b.get(key)
                if va != vb:
                    diffs[key] = {"from": va, "to": vb}
            if diffs:
                changed.append({"unique_id": uid, "name": b.get("name", a.get("name")), "changes": diffs})

        return json.dumps({
            "added_count":   len(added),
            "deleted_count": len(deleted),
            "changed_count": len(changed),
            "added":         added,
            "deleted":       deleted,
            "changed":       changed,
        }, indent=2)
