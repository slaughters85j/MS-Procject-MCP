"""
Project file lifecycle: open, create, inspect, save, close, recalculate, and XML round trips.
"""

import json

from ..com_helpers import (
    _find_app, _launch_app, get_app, get_proj, _get_mpd, _count_resources,
)
from ..com_write import to_com_date, commit, autosave_enabled, invoke_positional
from ..guards import validate_safe_path

# PjProjectUpdate (Project type library): pj0or100Percent=0, pj0to100Percent=1, pjReschedule=2.
PJ_0_OR_100, PJ_0_TO_100, PJ_RESCHEDULE = 0, 1, 2
PJ_DO_NOT_SAVE, PJ_SAVE = 0, 1
PROPERTY_FIELDS = {"title": "Title", "manager": "Manager", "company": "Company", "author": "Author",
                   "subject": "Subject", "start": "ProjectStart", "status_date": "StatusDate"}


def _require_saved_file(proj, action):
    if not proj.Path:
        raise ValueError(f"'{proj.Name}' has never been saved; use save_project_as before you {action}.")


def _save_as(app, file_path, format):
    """FileSaveAs in mpp or MS Project XML. Raises ValueError for unsupported formats."""
    fmt = format.lower().strip()
    if fmt == "mpp":
        app.FileSaveAs(Name=file_path, Format=0, Backup=False, ReadOnly=False)
    elif fmt == "xml":
        # FormatID is the 10th argument; passed by name it is ignored and a binary .mpp is written.
        invoke_positional(app, "FileSaveAs", file_path, None, None, None, None, None, None, None, None, "MSProject.XML")
    else:
        raise ValueError(f"Unsupported format '{format}'. Use 'mpp' or 'xml' (use export_csv for CSV).")


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
        Create a new blank, untitled project. It becomes the active project, so later writes go
        to it; it is not saved to disk until save_project_as is called.

        Args:
            title: Project title (default "New Project").
            start: Project start date as YYYY-MM-DD (optional).
        """
        app = _find_app()
        if app is None:
            app = _launch_app()
        app.FileNew(SummaryInfo=False)
        proj = app.ActiveProject
        proj.Title = title
        if start:
            proj.ProjectStart = to_com_date(proj, start, field="start")
        return json.dumps({"status": "created", "title": proj.Title, "name": proj.Name,
                           "start": str(proj.ProjectStart)[:10],
                           "note": "Untitled project is now active; call save_project_as to give it a file."}, indent=2)

    @mcp.tool()
    def get_project_info() -> str:
        """Get summary information about the currently active project."""
        app  = get_app()
        proj = get_proj(app)
        tasks = [t for t in proj.Tasks if t is not None]

        def fmt(dt):
            return str(dt)[:10] if dt and str(dt) != "NA" else None

        return json.dumps({
            "name":            proj.Name,
            "full_path":       proj.FullName,
            "title":           proj.Title or "",
            "manager":         proj.Manager or "",
            "company":         proj.Company or "",
            "author":          proj.Author or "",
            "subject":         proj.Subject or "",
            "start":           fmt(proj.ProjectStart),
            "finish":          fmt(proj.ProjectFinish),
            "status_date":     fmt(proj.StatusDate),
            "calendar":        proj.Calendar.Name,
            "tasks_total":     len(tasks),
            "summary_tasks":   sum(1 for t in tasks if t.Summary),
            "milestones":      sum(1 for t in tasks if t.Milestone),
            "critical_tasks":  sum(1 for t in tasks if t.Critical and not t.Summary),
            "resources":       _count_resources(proj),
            "hours_per_day":   proj.HoursPerDay,
            "minutes_per_day": _get_mpd(proj),
            "autosave":        autosave_enabled(),
        }, indent=2)

    @mcp.tool()
    def set_project_properties(properties_json: str) -> str:
        """
        Set project metadata properties. Unknown keys are rejected; dates are validated first.

        Args:
            properties_json: JSON object with any of: title, manager, company, author, subject,
                status_date (YYYY-MM-DD), start (YYYY-MM-DD).
                Example: '{"title": "EXPO 2030", "manager": "John", "company": "ERC"}'
        """
        props = json.loads(properties_json)
        if not isinstance(props, dict) or not props:
            raise ValueError("properties_json must be a non-empty JSON object.")
        unknown = [k for k in props if k not in PROPERTY_FIELDS]
        if unknown:
            raise ValueError(f"Unknown properties {unknown}. Supported: {list(PROPERTY_FIELDS)}.")
        app  = get_app()
        proj = get_proj(app)
        values = {k: to_com_date(proj, v, end_of_day=(k == "status_date"), field=k) if k in ("start", "status_date")
                  else str(v) for k, v in props.items()}
        for key, value in values.items():
            setattr(proj, PROPERTY_FIELDS[key], value)
        commit(app, proj)
        return json.dumps({"status": "updated", "changed": list(values)}, indent=2)

    @mcp.tool()
    def save_project() -> str:
        """Save the active project in place (an untitled project needs save_project_as)."""
        app  = get_app()
        proj = get_proj(app)
        _require_saved_file(proj, "save it")
        app.FileSave()
        return json.dumps({"status": "saved", "full_path": proj.FullName}, indent=2)

    @mcp.tool()
    def save_project_as(file_path: str, format: str = "mpp") -> str:
        """
        Save the active project to a new path. Like File > Save As, the open project then IS the
        new file: later writes and saves go to it, not to the original.
        format: 'mpp' (default) or 'xml'.
        """
        file_path = validate_safe_path(file_path)
        app = get_app()
        previous = app.ActiveProject.FullName
        _save_as(app, file_path, format)
        return json.dumps({"status": "saved", "full_path": app.ActiveProject.FullName, "format": format.lower(),
                           "previous_path": previous,
                           "note": "The active project is now the new file."}, indent=2)

    @mcp.tool()
    def close_project(save: bool = False) -> str:
        """Close the active project. Set save=True to save before closing."""
        app  = get_app()
        proj = get_proj(app)
        if save:
            _require_saved_file(proj, "close it with save=True")
        name = proj.Name
        app.FileCloseEx(Save=PJ_SAVE if save else PJ_DO_NOT_SAVE)
        return json.dumps({"status": "closed", "name": name, "saved": save}, indent=2)

    @mcp.tool()
    def import_xml(file_path: str) -> str:
        """
        Open an MS Project XML file (e.g. the consolidated EXPO 2030 roadmap).
        MS Project must be running.
        """
        return open_project(validate_safe_path(file_path))

    @mcp.tool()
    def export_xml(output_path: str) -> str:
        """
        Export the active project to MS Project XML format. The open project is unchanged
        and stays active (an XML save does not re-target it).
        """
        output_path = validate_safe_path(output_path)
        app  = get_app()
        proj = get_proj(app)
        original = proj.FullName
        _save_as(app, output_path, "xml")
        if app.ActiveProject.FullName != original:  # defensive: never leave the export copy active
            app.FileCloseEx(Save=PJ_DO_NOT_SAVE)
            app.FileOpenEx(Name=original)
        with open(output_path, "rb") as fp:
            if not fp.read(64).lstrip().startswith(b"<?xml"):
                raise RuntimeError("MS Project did not write XML to " + output_path)
        return json.dumps({"status": "exported", "path": output_path,
                           "active_project": app.ActiveProject.FullName}, indent=2)

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
        Update progress for all tasks through a given date (the weekly PMO ritual).

        Args:
            complete_through: Date as YYYY-MM-DD (end of that working day).
            set_0_or_100:     True: tasks are 0% or 100% only. False (default): partial percentages
                              for tasks in progress on the date.
        """
        app  = get_app()
        proj = get_proj(app)
        date = to_com_date(proj, complete_through, end_of_day=True, field="complete_through")
        app.UpdateProject(True, date, PJ_0_OR_100 if set_0_or_100 else PJ_0_TO_100)
        commit(app, proj)
        return json.dumps({"status": "updated", "complete_through": complete_through,
                           "set_0_or_100": set_0_or_100, "project": proj.Name}, indent=2)

    @mcp.tool()
    def reschedule_incomplete_work(reschedule_from: str = "") -> str:
        """
        Move remaining work on incomplete tasks to start after the given date
        (or the project status date if not specified). Actuals are not changed.

        Args:
            reschedule_from: Date as YYYY-MM-DD. Empty = use the project status date.
        """
        app  = get_app()
        proj = get_proj(app)
        if reschedule_from:
            date = to_com_date(proj, reschedule_from, end_of_day=True, field="reschedule_from")
        elif str(proj.StatusDate) != "NA":
            date = proj.StatusDate
        else:
            raise ValueError("No reschedule_from given and the project has no status date.")
        app.UpdateProject(True, date, PJ_RESCHEDULE)
        commit(app, proj)
        return json.dumps({"status": "rescheduled", "reschedule_from": str(date)[:10], "project": proj.Name}, indent=2)

    @mcp.tool()
    def undo_last(count: int = 1) -> str:
        """
        Undo the last N MS Project operations (max 10).

        Saving clears MS Project's undo history, and with MSPROJECT_AUTOSAVE on (the default)
        every write tool saves, so undo only reaches back to the last save. Run the server with
        MSPROJECT_AUTOSAVE=0 to keep an undo history across tool calls.

        Args:
            count: Number of undo steps (default 1, max 10).
        """
        count = max(1, min(count, 10))
        app = get_app()
        undone = 0
        for _ in range(count):
            try:
                app.EditUndo()
            except Exception:
                break
            undone += 1
        if undone == 0:
            return json.dumps({"error": "Nothing to undo: MS Project's undo history is empty (it is cleared on every save).",
                               "autosave": autosave_enabled()})
        return json.dumps({"status": "undone", "requested": count, "undo_count": undone}, indent=2)
