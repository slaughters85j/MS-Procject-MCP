"""
Calendar creation, deletion, and assignment to the project, tasks, and resources.
"""

import json

from ..com_helpers import get_app, get_proj, _find_task
from ..com_write import commit, resolve_resource, resolve_calendar as _calendar, invoke_positional


def _calendar_names(proj):
    return [c.Name for c in proj.BaseCalendars if c is not None]


def register_calendars_tools(mcp):
    """Register the calendars tools on the FastMCP instance."""

    @mcp.tool()
    def get_calendars() -> str:
        """List all base calendars in the project and which one is active."""
        app  = get_app()
        proj = get_proj(app)
        return json.dumps({"active_calendar": proj.Calendar.Name, "calendars": _calendar_names(proj)}, indent=2)

    @mcp.tool()
    def create_calendar(name: str, copy_from: str = "Standard") -> str:
        """
        Create a new base calendar, optionally copying from an existing one.

        Args:
            name:      Name for the new calendar (required, unique).
            copy_from: Existing calendar to copy from (default 'Standard').
        """
        app  = get_app()
        proj = get_proj(app)
        if not name.strip():
            return json.dumps({"error": "Calendar name is required."})
        source = _calendar(proj, copy_from)
        if name.lower() in [n.lower() for n in _calendar_names(proj)]:
            return json.dumps({"error": f"Calendar '{name}' already exists."})
        app.BaseCalendarCreate(Name=name, FromName=source.Name)
        commit(app, proj)
        return json.dumps({"status": "created", "name": name, "copied_from": source.Name,
                           "calendars": _calendar_names(proj)}, indent=2)

    @mcp.tool()
    def delete_calendar(calendar_name: str) -> str:
        """
        Delete a base calendar by name. Cannot delete the project calendar.
        Tasks and resources that used it fall back to the project calendar.

        Args:
            calendar_name: Name of the calendar to delete.
        """
        app  = get_app()
        proj = get_proj(app)
        cal = _calendar(proj, calendar_name)
        if cal.Name.lower() == proj.Calendar.Name.lower():
            return json.dumps({"error": "Cannot delete the active project calendar."})
        users = [r.Name for r in proj.Resources if r is not None and str(r.BaseCalendar).lower() == cal.Name.lower()]
        users += [f"task {t.UniqueID}" for t in proj.Tasks if t is not None and str(t.Calendar).lower() == cal.Name.lower()]
        name = cal.Name
        cal.Delete()
        commit(app, proj)
        return json.dumps({"status": "deleted", "calendar": name, "reassigned_to_project_calendar": users}, indent=2)

    @mcp.tool()
    def set_project_calendar(calendar_name: str) -> str:
        """
        Switch the active project's base calendar (via ProjectSummaryInfo, the documented API).
        The change is read back; if Project does not apply it, an error is returned.

        Args:
            calendar_name: Name of the base calendar to use (e.g. '24 Hours', 'Standard').
        """
        app  = get_app()
        proj = get_proj(app)
        cal = _calendar(proj, calendar_name)
        previous = proj.Calendar.Name
        if previous == cal.Name:
            return json.dumps({"status": "updated", "calendar": previous, "previous": previous, "changed": False}, indent=2)
        # Calendar is the 13th argument; by name MS Project ignores it or opens its dialog.
        invoke_positional(app, "ProjectSummaryInfo", proj.Name, *([None] * 11), cal.Name)
        if proj.Calendar.Name != cal.Name:
            return json.dumps({"error": f"MS Project did not apply calendar '{cal.Name}' (still '{proj.Calendar.Name}'). "
                                        "Change it in Project > Project Information."})
        commit(app, proj)
        return json.dumps({"status": "updated", "calendar": cal.Name, "previous": previous}, indent=2)

    @mcp.tool()
    def set_task_calendar(unique_id: int, calendar_name: str) -> str:
        """
        Set a task-level calendar override (e.g. 24/7 for commissioning phase).

        Args:
            unique_id:     Task UniqueID (required).
            calendar_name: Calendar name to apply, or empty string '' to clear.
        """
        app  = get_app()
        proj = get_proj(app)
        t = _find_task(proj, unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})
        name = _calendar(proj, calendar_name).Name if calendar_name else "None"
        previous = str(t.Calendar or "None")
        t.Calendar = name
        commit(app, proj)
        return json.dumps({"status": "updated", "unique_id": unique_id, "name": t.Name,
                           "calendar": calendar_name and name or "(cleared)", "previous": previous}, indent=2)

    @mcp.tool()
    def set_resource_calendar(resource_name: str, calendar_name: str) -> str:
        """
        Assign a specific base calendar to a resource (e.g., part-time, different timezone).

        Args:
            resource_name: Name of the resource.
            calendar_name: Name of the base calendar to assign.
        """
        app  = get_app()
        proj = get_proj(app)
        cal = _calendar(proj, calendar_name)
        r = resolve_resource(proj, resource_name)
        r.BaseCalendar = cal.Name
        commit(app, proj)
        return json.dumps({"status": "updated", "resource": r.Name, "calendar": cal.Name}, indent=2)
