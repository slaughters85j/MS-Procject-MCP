"""
Navigation and linking across several open projects and inserted subprojects.
"""

import json

from ..com_helpers import get_app, get_proj, _fmt_date, _find_task
from ..guards import validate_safe_path, is_dry_run, dry_run_response


def register_multiproject_tools(mcp):
    """Register the multiproject tools on the FastMCP instance."""

    @mcp.tool()
    def list_projects() -> str:
        """
        List all open projects in MS Project with metadata.
        Returns project count, which is active, and details for each.
        """
        app = get_app(require_project=False)

        projects = []
        active_name = ""
        try:
            active_name = app.ActiveProject.Name
        except Exception:
            pass

        for i in range(1, app.Projects.Count + 1):
            p = app.Projects(i)
            projects.append({
                "index":      i,
                "name":       p.Name,
                "full_path":  p.FullName,
                "task_count": p.Tasks.Count,
                "start":      _fmt_date(p.ProjectStart),
                "finish":     _fmt_date(p.ProjectFinish),
                "is_active":  p.Name == active_name,
            })

        return json.dumps({
            "count":    len(projects),
            "active":   active_name,
            "projects": projects,
        }, indent=2)


    @mcp.tool()
    def switch_project(name_or_index: str) -> str:
        """
        Switch the active project by name (substring match) or 1-based index.

        Args:
            name_or_index: Project name (case-insensitive substring) or numeric index.
        """
        app = get_app(require_project=False)

        if app.Projects.Count == 0:
            return json.dumps({"error": "No projects are open."})

        # Try as index first
        try:
            idx = int(name_or_index)
            if 1 <= idx <= app.Projects.Count:
                p = app.Projects(idx)
                p.Activate()
                return json.dumps({
                    "status":     "switched",
                    "name":       p.Name,
                    "full_path":  p.FullName,
                    "task_count": p.Tasks.Count,
                    "start":      _fmt_date(p.ProjectStart),
                    "finish":     _fmt_date(p.ProjectFinish),
                }, indent=2)
            else:
                return json.dumps({"error": f"Index {idx} out of range. Projects: 1-{app.Projects.Count}."})
        except ValueError:
            pass

        # Substring match on name
        query = name_or_index.lower()
        matches = []
        for i in range(1, app.Projects.Count + 1):
            p = app.Projects(i)
            if query in p.Name.lower():
                matches.append((i, p))

        if len(matches) == 0:
            names = [app.Projects(i).Name for i in range(1, app.Projects.Count + 1)]
            return json.dumps({"error": f"No project matching '{name_or_index}'. Open: {names}"})
        if len(matches) > 1:
            names = [m[1].Name for m in matches]
            return json.dumps({"error": f"Multiple matches for '{name_or_index}': {names}. Be more specific."})

        _, p = matches[0]
        try:
            active = app.ActiveProject.Name
            if active == p.Name:
                return json.dumps({
                    "status":     "already_active",
                    "name":       p.Name,
                    "full_path":  p.FullName,
                    "task_count": p.Tasks.Count,
                    "start":      _fmt_date(p.ProjectStart),
                    "finish":     _fmt_date(p.ProjectFinish),
                }, indent=2)
        except Exception:
            pass

        p.Activate()
        return json.dumps({
            "status":     "switched",
            "name":       p.Name,
            "full_path":  p.FullName,
            "task_count": p.Tasks.Count,
            "start":      _fmt_date(p.ProjectStart),
            "finish":     _fmt_date(p.ProjectFinish),
        }, indent=2)


    @mcp.tool()
    def insert_subproject(file_path: str, after_unique_id: int = 0) -> str:
        """
        Insert an external .mpp file as a subproject.

        Args:
            file_path:       Full path to the .mpp file to insert (required).
            after_unique_id: Insert after this task's UniqueID (0 = insert at end).
        """
        file_path = validate_safe_path(file_path)
        if is_dry_run():
            return dry_run_response("insert_subproject", {"file_path": file_path, "after_unique_id": after_unique_id})
        import os
        if not os.path.exists(file_path):
            return json.dumps({"error": f"File not found: {file_path}"})

        app  = get_app()
        proj = get_proj(app)

        count_before = proj.Tasks.Count

        # Insert by adding a task and setting its SubProject property.
        # (SubprojectInsert is not reliably exposed via COM in all versions.)
        try:
            import os as _os
            basename = _os.path.splitext(_os.path.basename(file_path))[0]
            if after_unique_id > 0:
                t = _find_task(proj, after_unique_id)
                if t is None:
                    return json.dumps({"error": f"Task UniqueID {after_unique_id} not found."})
                app.SelectRow(t.ID + 1, False)
                new_t = proj.Tasks.Add(basename)
            else:
                new_t = proj.Tasks.Add(basename)
            new_t.SubProject = file_path
        except Exception as e:
            return json.dumps({"error": f"Failed to insert subproject: {e}"})

        count_after = proj.Tasks.Count

        return json.dumps({
            "status":           "inserted",
            "file_path":        file_path,
            "inserted_after":   after_unique_id or "end",
            "task_count_before": count_before,
            "task_count_after":  count_after,
        }, indent=2)


    @mcp.tool()
    def cross_project_link(source_project: str, source_unique_id: int, target_project: str, target_unique_id: int, link_type: str = "FS") -> str:
        """
        Create a dependency link across open projects.

        Args:
            source_project:    Name of the predecessor's project.
            source_unique_id:  UniqueID of the predecessor task.
            target_project:    Name of the successor's project.
            target_unique_id:  UniqueID of the successor task.
            link_type:         'FS' (default), 'SS', 'FF', or 'SF'.
        """
        app = get_app(require_project=False)

        # Find source project and task
        src_proj = None
        for i in range(1, app.Projects.Count + 1):
            p = app.Projects(i)
            if p.Name.lower() == source_project.lower() or source_project.lower() in p.Name.lower():
                src_proj = p
                break
        if src_proj is None:
            return json.dumps({"error": f"Source project '{source_project}' not found."})

        src_task = _find_task(src_proj, source_unique_id)
        if src_task is None:
            return json.dumps({"error": f"Source task UniqueID {source_unique_id} not found in '{src_proj.Name}'."})

        # Find target project and task
        tgt_proj = None
        for i in range(1, app.Projects.Count + 1):
            p = app.Projects(i)
            if p.Name.lower() == target_project.lower() or target_project.lower() in p.Name.lower():
                tgt_proj = p
                break
        if tgt_proj is None:
            return json.dumps({"error": f"Target project '{target_project}' not found."})

        tgt_task = _find_task(tgt_proj, target_unique_id)
        if tgt_task is None:
            return json.dumps({"error": f"Target task UniqueID {target_unique_id} not found in '{tgt_proj.Name}'."})

        # Set cross-project predecessor using "ProjectName\TaskID" format
        pred_str = f"{src_proj.Name}\\{src_task.ID}{link_type}"
        existing = (tgt_task.Predecessors or "").strip()
        if existing:
            tgt_task.Predecessors = existing + "," + pred_str
        else:
            tgt_task.Predecessors = pred_str

        return json.dumps({
            "status":  "linked",
            "source":  {"project": src_proj.Name, "task": src_task.Name, "unique_id": source_unique_id},
            "target":  {"project": tgt_proj.Name, "task": tgt_task.Name, "unique_id": target_unique_id},
            "link_type": link_type,
        }, indent=2)
