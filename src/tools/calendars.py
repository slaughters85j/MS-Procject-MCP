"""
Calendar creation, deletion, and assignment to the project, tasks, and resources.
"""

import json

from ..com_helpers import get_app, get_proj, _find_task
from ..guards import is_dry_run, dry_run_response


def register_calendars_tools(mcp):
    """Register the calendars tools on the FastMCP instance."""

    @mcp.tool()
    def get_calendars() -> str:
        """List all base calendars in the project and which one is active."""
        app  = get_app()
        proj = get_proj(app)

        calendars = []
        try:
            for cal in proj.BaseCalendars:
                if cal is not None:
                    calendars.append(str(cal.Name))
        except Exception:
            pass

        active = ""
        try:
            active = str(proj.Calendar)
        except Exception:
            pass

        return json.dumps({
            "active_calendar": active,
            "calendars":       calendars,
        }, indent=2)


    @mcp.tool()
    def create_calendar(name: str, copy_from: str = "Standard") -> str:
        """
        Create a new base calendar, optionally copying from an existing one.

        Args:
            name:      Name for the new calendar (required).
            copy_from: Existing calendar to copy from (default 'Standard').
        """
        app  = get_app()
        proj = get_proj(app)

        # Validate copy_from exists
        valid_cals = []
        try:
            for cal in proj.BaseCalendars:
                if cal is not None:
                    valid_cals.append(str(cal.Name))
        except Exception:
            pass

        if copy_from not in valid_cals:
            return json.dumps({"error": f"Calendar '{copy_from}' not found. Available: {valid_cals}"})

        if name in valid_cals:
            return json.dumps({"error": f"Calendar '{name}' already exists."})

        try:
            app.BaseCalendarCreate(Name=name, FromName=copy_from)
        except Exception:
            try:
                app.BaseCalendarCreate(name, copy_from)
            except Exception as e:
                return json.dumps({"error": f"Failed to create calendar: {e}"})

        # Re-read calendar list
        calendars = []
        try:
            for cal in proj.BaseCalendars:
                if cal is not None:
                    calendars.append(str(cal.Name))
        except Exception:
            pass

        return json.dumps({
            "status":     "created",
            "name":       name,
            "copied_from": copy_from,
            "calendars":  calendars,
        }, indent=2)


    @mcp.tool()
    def delete_calendar(calendar_name: str) -> str:
        """
        Delete a base calendar by name. Cannot delete the project calendar.

        Args:
            calendar_name: Name of the calendar to delete.
        """
        if is_dry_run():
            return dry_run_response("delete_calendar", {"calendar_name": calendar_name})
        app  = get_app()
        proj = get_proj(app)

        try:
            proj_cal = str(proj.Calendar).lower()
        except Exception:
            proj_cal = "standard"
        if proj_cal == calendar_name.lower():
            return json.dumps({"error": "Cannot delete the active project calendar."})

        for c in proj.BaseCalendars:
            if c is not None and str(c.Name).lower() == calendar_name.lower():
                c.Delete()
                app.FileSave()
                return json.dumps({"status": "deleted", "calendar": calendar_name})

        return json.dumps({"error": f"Calendar '{calendar_name}' not found."})


    @mcp.tool()
    def set_project_calendar(calendar_name: str) -> str:
        """
        Switch the active project's base calendar.

        Args:
            calendar_name: Name of the base calendar to use (e.g. '24 Hours', 'Standard').
        """
        app  = get_app()
        proj = get_proj(app)

        # Validate
        valid_cals = []
        try:
            for cal in proj.BaseCalendars:
                if cal is not None:
                    valid_cals.append(str(cal.Name))
        except Exception:
            pass

        if calendar_name not in valid_cals:
            return json.dumps({"error": f"Calendar '{calendar_name}' not found. Available: {valid_cals}"})

        previous = ""
        try:
            previous = str(proj.Calendar)
        except Exception:
            pass

        # proj.Calendar is read-only in some COM bindings;
        # try multiple approaches to set it
        set_ok = False
        errors = []

        # Approach 1: direct property set
        try:
            proj.Calendar = calendar_name
            set_ok = True
        except Exception as e:
            errors.append(f"direct: {e}")

        # Approach 2: use the Calendar object from BaseCalendars
        if not set_ok:
            try:
                for cal in proj.BaseCalendars:
                    if cal is not None and str(cal.Name) == calendar_name:
                        proj.Calendar = cal
                        set_ok = True
                        break
            except Exception as e:
                errors.append(f"object: {e}")

        # Approach 3: use _oleobj_ InvokeTypes to force property set
        if not set_ok:
            try:
                import pythoncom
                # Calendar property dispid — try to find via QueryInterface
                proj._oleobj_.InvokeTypes(
                    0x30, 0, pythoncom.DISPATCH_PROPERTYPUT,
                    (24, 0),  # VT_VOID return
                    ((8, 1),),  # VT_BSTR input
                    calendar_name
                )
                set_ok = True
            except Exception as e:
                errors.append(f"oleobj: {e}")

        if not set_ok:
            return json.dumps({"error": f"Could not set calendar. Tried: {errors}"})

        app.FileSave()

        return json.dumps({
            "status":   "updated",
            "calendar": calendar_name,
            "previous": previous,
        }, indent=2)


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

        # Validate calendar exists (if not clearing)
        if calendar_name:
            valid_cals = []
            try:
                for cal in proj.BaseCalendars:
                    if cal is not None:
                        valid_cals.append(str(cal.Name))
            except Exception:
                pass
            if calendar_name not in valid_cals:
                return json.dumps({"error": f"Calendar '{calendar_name}' not found. Available: {valid_cals}"})

        previous = ""
        try:
            previous = str(t.Calendar) if t.Calendar else ""
        except Exception:
            pass

        try:
            if calendar_name:
                t.Calendar = calendar_name
            else:
                t.Calendar = ""
        except Exception as e:
            return json.dumps({"error": f"Failed to set task calendar: {e}"})

        return json.dumps({
            "status":    "updated",
            "unique_id": unique_id,
            "name":      t.Name,
            "calendar":  calendar_name or "(cleared)",
            "previous":  previous,
        }, indent=2)


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

        # Verify calendar exists
        cal_found = False
        for c in proj.BaseCalendars:
            if c is not None and str(c.Name).lower() == calendar_name.lower():
                cal_found = True
                break
        if not cal_found:
            return json.dumps({"error": f"Calendar '{calendar_name}' not found."})

        for r in proj.Resources:
            if r is not None and r.Name and r.Name.lower() == resource_name.lower():
                r.BaseCalendar = calendar_name
                app.FileSave()
                return json.dumps({
                    "status":   "updated",
                    "resource": r.Name,
                    "calendar": calendar_name,
                }, indent=2)

        return json.dumps({"error": f"Resource '{resource_name}' not found."})
