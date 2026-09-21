"""
Calendar exceptions and working hours.
"""

import json

from ..com_helpers import get_app, get_proj, _parse_date, _fmt_date
from ..guards import is_dry_run, dry_run_response


def register_calendar_exceptions_tools(mcp):
    """Register the calendar exceptions tools on the FastMCP instance."""

    @mcp.tool()
    def set_calendar_exception(
        calendar_name: str,
        name: str,
        start: str,
        finish: str,
        working: bool = False,
    ) -> str:
        """
        Add a holiday or exception to a base calendar.

        Args:
            calendar_name: Name of the base calendar (e.g. 'Standard').
            name:          Exception name (e.g. 'National Day').
            start:         Start date as YYYY-MM-DD.
            finish:        End date as YYYY-MM-DD (same as start for single day).
            working:       True for a working exception, False for non-working/holiday (default).
        """
        app  = get_app()
        proj = get_proj(app)

        # Validate calendar exists
        valid_cals = []
        try:
            for cal in proj.BaseCalendars:
                if cal is not None:
                    valid_cals.append(str(cal.Name))
        except Exception:
            pass

        if calendar_name not in valid_cals:
            return json.dumps({"error": f"Calendar '{calendar_name}' not found. Available: {valid_cals}"})

        try:
            # Use the Calendar.Exceptions collection for date-range exceptions
            cal = None
            for c in proj.BaseCalendars:
                if c is not None and str(c.Name) == calendar_name:
                    cal = c
                    break

            # pjCalendarExceptionDaily = 1
            start_dt  = _parse_date(start)
            finish_dt = _parse_date(finish)
            exc = cal.Exceptions.Add(1, start_dt, finish_dt, name)
        except Exception as e:
            return json.dumps({"error": f"Failed to set exception: {e}"})

        app.FileSave()
        return json.dumps({
            "status":   "created",
            "calendar": calendar_name,
            "exception": name,
            "start":    start,
            "finish":   finish,
            "working":  working,
        }, indent=2)


    @mcp.tool()
    def list_calendar_exceptions(calendar_name: str = "") -> str:
        """
        List all exceptions (holidays, non-working days) defined on a calendar.
        If calendar_name is empty, uses the project calendar.

        Args:
            calendar_name: Name of the base calendar. Empty = project calendar.
        """
        app  = get_app()
        proj = get_proj(app)

        if not calendar_name:
            try:
                calendar_name = str(proj.Calendar)
            except Exception:
                calendar_name = "Standard"

        cal = None
        for c in proj.BaseCalendars:
            if c is not None and str(c.Name).lower() == str(calendar_name).lower():
                cal = c
                break
        if cal is None:
            return json.dumps({"error": f"Calendar '{calendar_name}' not found."})

        exceptions = []
        try:
            for exc in cal.Exceptions:
                exceptions.append({
                    "name":   str(exc.Name),
                    "start":  _fmt_date(exc.Start),
                    "finish": _fmt_date(exc.Finish),
                    "type":   exc.Type,
                })
        except Exception:
            pass  # Some calendars have no Exceptions collection

        return json.dumps({
            "calendar":   str(cal.Name),
            "count":      len(exceptions),
            "exceptions": exceptions,
        }, indent=2)


    @mcp.tool()
    def delete_calendar_exception(calendar_name: str, exception_name: str) -> str:
        """
        Remove a specific exception (holiday/non-working day) from a calendar.

        Args:
            calendar_name:  Name of the base calendar.
            exception_name: Name of the exception to remove.
        """
        if is_dry_run():
            return dry_run_response("delete_calendar_exception", {"calendar_name": calendar_name, "exception_name": exception_name})
        app  = get_app()
        proj = get_proj(app)

        cal = None
        for c in proj.BaseCalendars:
            if c is not None and str(c.Name).lower() == calendar_name.lower():
                cal = c
                break
        if cal is None:
            return json.dumps({"error": f"Calendar '{calendar_name}' not found."})

        try:
            for exc in cal.Exceptions:
                if str(exc.Name).lower() == exception_name.lower():
                    exc.Delete()
                    app.FileSave()
                    return json.dumps({
                        "status":    "deleted",
                        "calendar":  calendar_name,
                        "exception": exception_name,
                    })
        except Exception as e:
            return json.dumps({"error": f"Failed to access exceptions: {e}"})

        return json.dumps({"error": f"Exception '{exception_name}' not found in calendar '{calendar_name}'."})


    @mcp.tool()
    def set_working_hours(calendar_name: str, day: int, shifts_json: str) -> str:
        """
        Modify working hours for a specific day of the week in a calendar.

        Args:
            calendar_name: Name of the base calendar.
            day:           Day number (1=Sunday, 2=Monday, ..., 7=Saturday).
            shifts_json:   JSON array of shifts, e.g. [["08:00","12:00"],["13:00","17:00"]].
                           Empty array [] marks the day as non-working.
        """
        app  = get_app()
        proj = get_proj(app)

        if day < 1 or day > 7:
            return json.dumps({"error": "day must be 1 (Sunday) through 7 (Saturday)."})

        cal = None
        for c in proj.BaseCalendars:
            if c is not None and str(c.Name).lower() == calendar_name.lower():
                cal = c
                break
        if cal is None:
            return json.dumps({"error": f"Calendar '{calendar_name}' not found."})

        shifts = json.loads(shifts_json)

        wd = cal.WeekDays(day)

        if not shifts:
            # Mark as non-working
            wd.Working = False
            app.FileSave()
            return json.dumps({
                "status":   "updated",
                "calendar": cal.Name,
                "day":      day,
                "working":  False,
            }, indent=2)

        wd.Working = True

        # Set shifts using ShiftN Start/Finish properties (1-indexed)
        # Clear all 5 shifts first, then set the provided ones
        shift_attrs = [
            ("Shift1Start", "Shift1Finish"),
            ("Shift2Start", "Shift2Finish"),
            ("Shift3Start", "Shift3Finish"),
            ("Shift4Start", "Shift4Finish"),
            ("Shift5Start", "Shift5Finish"),
        ]

        for i, (s_attr, f_attr) in enumerate(shift_attrs):
            try:
                if i < len(shifts):
                    setattr(wd, s_attr, shifts[i][0])
                    setattr(wd, f_attr, shifts[i][1])
                else:
                    # Clear unused shifts
                    setattr(wd, s_attr, "")
                    setattr(wd, f_attr, "")
            except Exception:
                pass

        app.FileSave()
        return json.dumps({
            "status":   "updated",
            "calendar": cal.Name,
            "day":      day,
            "working":  True,
            "shifts":   shifts[:5],
        }, indent=2)
