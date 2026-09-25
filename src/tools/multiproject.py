"""
Navigation and linking across several open projects and inserted subprojects.
"""

import json
import os

from ..com_helpers import get_app, get_proj, _fmt_date, _find_task
from ..com_write import commit, activate_project, LINK_TYPES
from ..guards import validate_safe_path


def _resolve_project(app, name):
    """
    Find one open project by exact name or full path (case-insensitive), falling back to a
    substring match only when it is unambiguous. Raises ValueError otherwise.
    """
    open_projects = [app.Projects(i) for i in range(1, app.Projects.Count + 1)]
    query = (name or "").strip().lower()
    exact = [p for p in open_projects if query in (p.Name.lower(), p.FullName.lower())]
    if len(exact) == 1:
        return exact[0]
    partial = [p for p in open_projects if query and query in p.Name.lower()]
    if len(partial) == 1 and not exact:
        return partial[0]
    names = [p.Name for p in (exact or partial or open_projects)]
    if exact or partial:
        raise ValueError(f"Project '{name}' is ambiguous: {names}. Use the exact name or full path.")
    raise ValueError(f"No open project matching '{name}'. Open: {names}")


def _project_summary(p, status):
    return {"status": status, "name": p.Name, "full_path": p.FullName, "task_count": p.Tasks.Count,
            "start": _fmt_date(p.ProjectStart), "finish": _fmt_date(p.ProjectFinish)}


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
        Switch the active project by exact name/path, unambiguous name substring, or 1-based index.

        Args:
            name_or_index: Project name or full path (exact match preferred), or numeric index.
        """
        app = get_app(require_project=False)

        if app.Projects.Count == 0:
            return json.dumps({"error": "No projects are open."})

        # Try as index first
        try:
            idx = int(name_or_index)
            if 1 <= idx <= app.Projects.Count:
                p = app.Projects(idx)
                activate_project(app, p)
                return json.dumps(_project_summary(p, "switched"), indent=2)
            else:
                return json.dumps({"error": f"Index {idx} out of range. Projects: 1-{app.Projects.Count}."})
        except ValueError:
            pass

        p = _resolve_project(app, name_or_index)
        if app.ActiveProject.FullName == p.FullName:
            return json.dumps(_project_summary(p, "already_active"), indent=2)
        activate_project(app, p)
        return json.dumps(_project_summary(p, "switched"), indent=2)


    @mcp.tool()
    def insert_subproject(file_path: str, after_unique_id: int = 0) -> str:
        """
        Insert an external .mpp file as a subproject.

        Args:
            file_path:       Full path to the .mpp file to insert (required).
            after_unique_id: Insert directly after this task's UniqueID (0 = insert at end).
        """
        file_path = validate_safe_path(file_path)
        if not os.path.exists(file_path):
            return json.dumps({"error": f"File not found: {file_path}"})
        app  = get_app()
        proj = get_proj(app)
        before = None
        if after_unique_id:
            anchor = _find_task(proj, after_unique_id)
            if anchor is None:
                return json.dumps({"error": f"Task UniqueID {after_unique_id} not found."})
            before = anchor.ID + 1 if anchor.ID < proj.Tasks.Count else None
        name = os.path.splitext(os.path.basename(file_path))[0]
        new_t = proj.Tasks.Add(name, before) if before else proj.Tasks.Add(name)
        try:
            new_t.SubProject = file_path
        except Exception:
            new_t.Delete()
            raise
        commit(app, proj)
        return json.dumps({"status": "inserted", "file_path": file_path, "unique_id": new_t.UniqueID,
                           "id": new_t.ID, "inserted_after": after_unique_id or "end"}, indent=2)

    @mcp.tool()
    def cross_project_link(source_project: str, source_unique_id: int, target_project: str, target_unique_id: int, link_type: str = "FS") -> str:
        """
        Create a dependency link across open projects.

        Args:
            source_project:    Name or full path of the predecessor's project (exact match preferred).
            source_unique_id:  UniqueID of the predecessor task.
            target_project:    Name or full path of the successor's project (exact match preferred).
            target_unique_id:  UniqueID of the successor task.
            link_type:         'FS' (default), 'SS', 'FF', or 'SF'.
        """
        code = str(link_type).upper().strip()
        if code not in LINK_TYPES:
            return json.dumps({"error": f"Invalid link_type '{link_type}'. Use FS, SS, FF, or SF."})
        app = get_app(require_project=False)
        src_proj = _resolve_project(app, source_project)
        tgt_proj = _resolve_project(app, target_project)
        src_task = _find_task(src_proj, source_unique_id)
        if src_task is None:
            return json.dumps({"error": f"Source task UniqueID {source_unique_id} not found in '{src_proj.Name}'."})
        tgt_task = _find_task(tgt_proj, target_unique_id)
        if tgt_task is None:
            return json.dumps({"error": f"Target task UniqueID {target_unique_id} not found in '{tgt_proj.Name}'."})

        # The object API creates same-file and cross-file (external) links alike, without
        # composing the Predecessors text (whose list separator depends on the Windows locale).
        tgt_task.TaskDependencies.Add(From=src_task, Type=LINK_TYPES[code], Lag=0)
        commit(app, tgt_proj)
        return json.dumps({
            "status":    "linked",
            "source":    {"project": src_proj.Name, "full_path": src_proj.FullName, "task": src_task.Name, "unique_id": source_unique_id},
            "target":    {"project": tgt_proj.Name, "full_path": tgt_proj.FullName, "task": tgt_task.Name, "unique_id": target_unique_id},
            "link_type": code,
            "target_predecessors": tgt_task.Predecessors,
        }, indent=2)
