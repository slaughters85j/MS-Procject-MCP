"""
Calendar exceptions and working hours.

Both WeekDay and Exception objects expose Shift1..Shift5 (each with Start/Finish/Clear), so one
helper validates and writes shifts for both. Times go to COM as UTC-aware datetimes on
1899-12-30 (COM's time-only date) so neither locale nor timezone can change them.
"""

import datetime
import json
import re

from ..com_helpers import get_app, get_proj, _fmt_date
from ..com_write import parse_iso, to_com_date, commit, resolve_calendar

_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$|^24:00$")
DEFAULT_WORKING_SHIFTS = [["08:00", "12:00"], ["13:00", "17:00"]]


def _minutes(text):
    if not isinstance(text, str) or not _TIME.match(text.strip()):
        raise ValueError(f"Invalid time '{text}'. Use HH:MM (24-hour, 00:00-24:00).")
    h, m = text.strip().split(":")
    return int(h) * 60 + int(m)


def _validate_shifts(shifts):
    """Up to 5 [start, finish] pairs, each finish after its start, in order and non-overlapping."""
    if not isinstance(shifts, list) or len(shifts) > 5:
        raise ValueError("shifts must be a JSON array of at most 5 [\"HH:MM\", \"HH:MM\"] pairs.")
    previous_end = -1
    out = []
    for pair in shifts:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError(f"Each shift must be [start, finish]; got {pair}.")
        start, finish = _minutes(pair[0]), _minutes(pair[1])
        if finish <= start or start < previous_end:
            raise ValueError(f"Shift {pair} must end after it starts and not overlap the previous shift.")
        previous_end = finish
        out.append((start, finish))
    return out


def _hhmm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _com_time(minutes):
    base = datetime.datetime(1899, 12, 30, tzinfo=datetime.timezone.utc)
    return base + datetime.timedelta(minutes=minutes)


def _write_shifts(owner, shifts):
    """Clear all five shifts on a WeekDay/Exception, then write the validated ones."""
    for i in range(5, 0, -1):
        getattr(owner, f"Shift{i}").Clear()
    for i, (start, finish) in enumerate(shifts, 1):
        shift = getattr(owner, f"Shift{i}")
        shift.Start = _com_time(start)
        shift.Finish = _com_time(finish)


def register_calendar_exceptions_tools(mcp):
    """Register the calendar exceptions tools on the FastMCP instance."""

    @mcp.tool()
    def set_calendar_exception(
        calendar_name: str,
        name: str,
        start: str,
        finish: str,
        working: bool = False,
        shifts_json: str = "",
    ) -> str:
        """
        Add a holiday (non-working) or a working exception to a base calendar.

        Args:
            calendar_name: Name of the base calendar (e.g. 'Standard').
            name:          Exception name (e.g. 'National Day'); must be unique in the calendar.
            start:         Start date as YYYY-MM-DD.
            finish:        End date as YYYY-MM-DD (same as start for a single day; not before start).
            working:       True for a working exception, False for non-working/holiday (default).
            shifts_json:   Working hours for a working exception, e.g. [["08:00","12:00"],["13:00","17:00"]]
                           (default: 08:00-12:00 and 13:00-17:00). Ignored for holidays.
        """
        if not name.strip():
            return json.dumps({"error": "Exception name is required."})
        if parse_iso(finish, "finish")[0] < parse_iso(start, "start")[0]:
            return json.dumps({"error": "finish is before start."})
        shifts = _validate_shifts(json.loads(shifts_json) if shifts_json else DEFAULT_WORKING_SHIFTS) if working else []
        app  = get_app()
        proj = get_proj(app)
        cal = resolve_calendar(proj, calendar_name)
        if any(e.Name.lower() == name.strip().lower() for e in cal.Exceptions):
            return json.dumps({"error": f"Calendar '{cal.Name}' already has an exception named '{name}'."})

        exc = cal.Exceptions.Add(1, to_com_date(proj, start + "T00:00"), to_com_date(proj, finish + "T00:00"))
        try:
            exc.Name = name.strip()  # Exceptions.Add ignores the Name argument; set it afterwards
            if working:
                _write_shifts(exc, shifts)
        except Exception:
            exc.Delete()
            raise
        commit(app, proj)
        return json.dumps({"status": "created", "calendar": cal.Name, "exception": exc.Name,
                           "start": _fmt_date(exc.Start), "finish": _fmt_date(exc.Finish),
                           "working": working, "shifts": [[_hhmm(a), _hhmm(b)] for a, b in shifts]}, indent=2)

    @mcp.tool()
    def list_calendar_exceptions(calendar_name: str = "") -> str:
        """
        List all exceptions (holidays, working exceptions) defined on a calendar.
        If calendar_name is empty, uses the project calendar.

        Args:
            calendar_name: Name of the base calendar. Empty = project calendar.
        """
        app  = get_app()
        proj = get_proj(app)
        cal = resolve_calendar(proj, calendar_name) if calendar_name else proj.Calendar
        exceptions = [{
            "name":    exc.Name,
            "start":   _fmt_date(exc.Start),
            "finish":  _fmt_date(exc.Finish),
            "working": bool(exc.Shift1.Start),
            "type":    exc.Type,
        } for exc in cal.Exceptions]
        return json.dumps({"calendar": cal.Name, "count": len(exceptions), "exceptions": exceptions}, indent=2)

    @mcp.tool()
    def delete_calendar_exception(calendar_name: str, exception_name: str) -> str:
        """
        Remove a specific exception (holiday/working exception) from a calendar.

        Args:
            calendar_name:  Name of the base calendar.
            exception_name: Name of the exception to remove (case-insensitive).
        """
        app  = get_app()
        proj = get_proj(app)
        cal = resolve_calendar(proj, calendar_name)
        exc = next((e for e in cal.Exceptions if e.Name.lower() == exception_name.strip().lower()), None)
        if exc is None:
            return json.dumps({"error": f"Exception '{exception_name}' not found in calendar '{cal.Name}'. "
                                        f"Existing: {[e.Name for e in cal.Exceptions]}"})
        exc.Delete()
        commit(app, proj)
        return json.dumps({"status": "deleted", "calendar": cal.Name, "exception": exception_name})

    @mcp.tool()
    def set_working_hours(calendar_name: str, day: int, shifts_json: str) -> str:
        """
        Replace the working hours for one day of the week in a calendar.

        Args:
            calendar_name: Name of the base calendar.
            day:           Day number (1=Sunday, 2=Monday, ..., 7=Saturday).
            shifts_json:   JSON array of up to 5 shifts, e.g. [["08:00","12:00"],["13:00","17:00"]].
                           Any shifts not listed are cleared. Empty array [] marks the day as non-working.
        """
        if day < 1 or day > 7:
            return json.dumps({"error": "day must be 1 (Sunday) through 7 (Saturday)."})
        shifts = _validate_shifts(json.loads(shifts_json))
        app  = get_app()
        proj = get_proj(app)
        cal = resolve_calendar(proj, calendar_name)
        wd = cal.WeekDays(day)
        if shifts:
            wd.Working = True
            _write_shifts(wd, shifts)
        else:
            wd.Working = False
        commit(app, proj)
        actual = [[str(getattr(wd, f"Shift{i}").Start), str(getattr(wd, f"Shift{i}").Finish)]
                  for i in range(1, 6) if getattr(wd, f"Shift{i}").Start]
        return json.dumps({"status": "updated", "calendar": cal.Name, "day": day,
                           "working": bool(wd.Working), "shifts": actual if wd.Working else []}, indent=2)
