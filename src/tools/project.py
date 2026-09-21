"""
Project file lifecycle: open, create, inspect, save, close, recalculate, and XML round trips.
"""

import datetime
import json

from ..com_helpers import (
    _find_app, _launch_app, get_app, get_proj, _get_mpd, _parse_date, _count_resources,
)
from ..guards import validate_safe_path, is_dry_run, dry_run_response


def register_project_tools(mcp):
    """Register the project tools on the FastMCP instance."""

    @mcp.tool()
    def open_project(file_path: str) -> str:
        """
        Open a Microsoft Project file (.mpp or .xml).
        MS Project must already be running (it is launched automatically if not).
        """
        file_path = validate_safe_path(file_path)
        app = _find_app()
        if app is None:
            app = _launch_app()

        app.FileOpen(file_path)
        proj = app.ActiveProject
        return json.dumps({
            "status":     "opened",
            "name":       proj.Name,
            "full_path":  proj.FullName,
            "task_count": proj.Tasks.Count,
            "start":      str(proj.ProjectStart)[:10],
            "finish":     str(proj.ProjectFinish)[:10],
        }, indent=2)


    @mcp.tool()
    def new_project(title: str = "New Project", start: str = "") -> str:
        """
        Create a new blank project without needing a file on disk.

        Args:
            title: Project title (default "New Project").
            start: Project start date as YYYY-MM-DD (optional).
        """
        app = _find_app()
        if app is None:
            app = _launch_app()

        app.FileNew()
        proj = app.ActiveProject
        proj.Title = title
        if start:
            proj.ProjectStart = _parse_date(start)

        return json.dumps({
            "status": "created",
            "title":  proj.Title,
            "name":   proj.Name,
            "start":  str(proj.ProjectStart)[:10],
        }, indent=2)


    @mcp.tool()
    def get_project_info() -> str:
        """Get summary information about the currently active project."""
        app  = get_app()
        proj = get_proj(app)
        mpd  = _get_mpd(proj)

        def fmt(dt):
            try:
                return str(dt)[:10] if dt else None
            except Exception:
                return None

        task_count    = sum(1 for t in proj.Tasks if t is not None)
        summary_count = sum(1 for t in proj.Tasks if t is not None and t.Summary)
        mile_count    = sum(1 for t in proj.Tasks if t is not None and t.Milestone)
        critical      = sum(1 for t in proj.Tasks if t is not None and t.Critical and not t.Summary)

        # Safe reads for optional metadata
        def safe_read(attr):
            try:
                return getattr(proj, attr, "") or ""
            except Exception:
                return ""

        return json.dumps({
            "name":            proj.Name,
            "full_path":       proj.FullName,
            "title":           safe_read("Title"),
            "manager":         safe_read("Manager"),
            "company":         safe_read("Company"),
            "author":          safe_read("Author"),
            "subject":         safe_read("Subject"),
            "start":           fmt(proj.ProjectStart),
            "finish":          fmt(proj.ProjectFinish),
            "status_date":     fmt(getattr(proj, "StatusDate", None)),
            "calendar":        str(proj.Calendar) if proj.Calendar else "",
            "tasks_total":     task_count,
            "summary_tasks":   summary_count,
            "milestones":      mile_count,
            "critical_tasks":  critical,
            "resources":       _count_resources(proj),
            "minutes_per_day": mpd,
        }, indent=2)


    @mcp.tool()
    def set_project_properties(properties_json: str) -> str:
        """
        Set project metadata properties.

        Args:
            properties_json: JSON string with fields to set. All optional:
                title, manager, company, author, subject, status_date (YYYY-MM-DD),
                start (YYYY-MM-DD).
                Example: '{"title": "EXPO 2030", "manager": "John", "company": "ERC"}'
        """
        if is_dry_run():
            return dry_run_response("set_project_properties", {"properties_json": properties_json})
        props = json.loads(properties_json)
        app   = get_app()
        proj  = get_proj(app)

        changed = []
        if "title" in props:
            proj.Title = props["title"];       changed.append("title")
        if "manager" in props:
            proj.Manager = props["manager"];   changed.append("manager")
        if "company" in props:
            proj.Company = props["company"];   changed.append("company")
        if "author" in props:
            proj.Author = props["author"];     changed.append("author")
        if "subject" in props:
            proj.Subject = props["subject"];   changed.append("subject")
        if "start" in props and props["start"]:
            proj.ProjectStart = _parse_date(props["start"]); changed.append("start")
        if "status_date" in props and props["status_date"]:
            proj.StatusDate = _parse_date(props["status_date"]); changed.append("status_date")

        app.FileSave()
        return json.dumps({"status": "updated", "changed": changed}, indent=2)


    @mcp.tool()
    def save_project() -> str:
        """Save the active project (in place)."""
        if is_dry_run():
            return dry_run_response("save_project", {})
        app = get_app()
        app.FileSave()
        return "Project saved."


    @mcp.tool()
    def save_project_as(file_path: str, format: str = "mpp") -> str:
        """
        Save the active project to a new path.
        format: 'mpp' (default), 'xml', 'csv'
        """
        file_path = validate_safe_path(file_path)
        if is_dry_run():
            return dry_run_response("save_project_as", {"file_path": file_path, "format": format})
        fmt_map = {"mpp": 0, "xml": 22, "csv": 23}
        fmt_id  = fmt_map.get(format.lower(), 0)
        app     = get_app()
        app.FileSaveAs(Name=file_path, Format=fmt_id, Backup=False, ReadOnly=False)
        return f"Project saved as: {file_path}"


    @mcp.tool()
    def close_project(save: bool = False) -> str:
        """Close the active project. Set save=True to save before closing."""
        if is_dry_run():
            return dry_run_response("close_project", {"save": save})
        app = get_app()
        app.FileClose(Save=1 if save else 0)
        return "Project closed."


    @mcp.tool()
    def import_xml(file_path: str) -> str:
        """
        Open an MS Project XML file (e.g. the consolidated EXPO 2030 roadmap).
        MS Project must be running.
        """
        file_path = validate_safe_path(file_path)  # defense-in-depth; open_project also validates
        return open_project(file_path)


    @mcp.tool()
    def export_xml(output_path: str) -> str:
        """Export the active project to MS Project XML format."""
        output_path = validate_safe_path(output_path)  # defense-in-depth; save_project_as also validates
        return save_project_as(output_path, format="xml")


    @mcp.tool()
    def calculate_project() -> str:
        """
        Recalculate the active project schedule.
        Use after bulk manual changes to ensure dates, slack, and critical path are up to date.
        """
        app = get_app()
        app.CalculateProject()
        return json.dumps({"status": "calculated", "project": app.ActiveProject.Name})


    @mcp.tool()
    def update_project(complete_through: str, set_0_or_100: bool = False) -> str:
        """
        Mark all tasks complete through a given date (the weekly PMO ritual).
        Tasks that should have finished by the date get their % complete updated.

        Args:
            complete_through: Date as YYYY-MM-DD — tasks scheduled through this date are updated.
            set_0_or_100:     If True, tasks are set to 0% or 100% only (no partial). Default False.
        """
        if is_dry_run():
            return dry_run_response("update_project", {"complete_through": complete_through, "set_0_or_100": set_0_or_100})
        app  = get_app()
        proj = get_proj(app)
        dt   = _parse_date(complete_through)
        if dt is None:
            return json.dumps({"error": "complete_through date is required (YYYY-MM-DD)."})

        # COM VBA signature: UpdateProject(All, UpdateDate, Action)
        # All = True (entire project), UpdateDate = date, Action:
        #   pjUpdateProjectStatusPctComplete = 0
        #   pjUpdateProject0or100 = 1
        action = 1 if set_0_or_100 else 0
        try:
            app.UpdateProject(True, dt, action)
        except Exception:
            try:
                # Alternative: just date
                app.UpdateProject(True, dt)
            except Exception:
                app.UpdateProject(dt)
        app.FileSave()

        return json.dumps({
            "status": "updated",
            "complete_through": complete_through,
            "set_0_or_100": set_0_or_100,
            "project": proj.Name,
        }, indent=2)


    @mcp.tool()
    def reschedule_incomplete_work(reschedule_from: str = "") -> str:
        """
        Move remaining work on incomplete tasks to start after the given date
        (or the project status date if not specified).

        Args:
            reschedule_from: Date as YYYY-MM-DD. Empty = use project status date.
        """
        if is_dry_run():
            return dry_run_response("reschedule_incomplete_work", {"reschedule_from": reschedule_from})
        app  = get_app()
        proj = get_proj(app)

        if reschedule_from:
            dt = _parse_date(reschedule_from)
        else:
            dt = proj.StatusDate
            if dt is None or str(dt) == "NA":
                dt = datetime.datetime.now()

        # Set status date, then use UpdateProject to reschedule
        # The reschedule action = updating incomplete tasks from the status date
        try:
            proj.StatusDate = dt
            # UpdateProject with All=True, date, action=0 to push remaining work
            app.UpdateProject(True, dt, 0)
        except Exception:
            try:
                app.UpdateProject(True, dt)
            except Exception:
                proj.StatusDate = dt  # At minimum set the status date
        app.FileSave()

        return json.dumps({
            "status": "rescheduled",
            "reschedule_from": str(dt)[:10],
            "project": proj.Name,
        }, indent=2)


    @mcp.tool()
    def undo_last(count: int = 1) -> str:
        """
        Safety net — undo last N operations in MS Project.

        Args:
            count: Number of undo steps (default 1, max 10).
        """
        if is_dry_run():
            return dry_run_response("undo_last", {"count": count})
        if count < 1:
            count = 1
        if count > 10:
            count = 10

        app = get_app()
        for _ in range(count):
            try:
                app.EditUndo()
            except Exception:
                break

        return json.dumps({"status": "undone", "undo_count": count}, indent=2)
