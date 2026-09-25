"""
Write-side COM helpers shared by the mutating tools: date conversion that survives pywin32's
timezone handling, the save policy applied after a mutation, and batched recalculation.
"""

import datetime
import os
from contextlib import contextmanager

_UTC = datetime.timezone.utc
_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S")

# PjTimescaleUnit values for TimeScaleData (Weeks=3, Days=4, Months=2).
TIMESCALES = {"daily": 4, "weekly": 3, "monthly": 2}
# pjTaskLinkType values and their Predecessors-string codes.
LINK_TYPES = {"FF": 0, "FS": 1, "SF": 2, "SS": 3}
RAG_VALUES = ("Red", "Amber", "Green")


def parse_iso(s, field="date"):
    """
    Parse 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM[:SS]'. Returns (naive datetime, has_time).
    Raises ValueError naming the field when the value does not parse.
    """
    text = (s or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt), fmt != "%Y-%m-%d"
        except ValueError:
            continue
    raise ValueError(f"Invalid {field} '{s}'. Use YYYY-MM-DD (optionally with THH:MM).")


def _default_time(proj, attr, fallback):
    """The project's default start or finish time of day (e.g. 08:00 / 17:00)."""
    try:
        value = getattr(proj, attr)
        return datetime.time(value.hour, value.minute)
    except Exception:
        return fallback


def to_com_date(proj, s, end_of_day=False, field="date"):
    """
    Convert a user date string to a datetime that COM stores unchanged.

    pywin32 treats a naive datetime as local time and converts it to UTC before building the
    VARIANT DATE, so 2031-06-01 00:00 lands in Project as 04:00 in EDT (and on the previous day
    east of UTC). A UTC-aware datetime is passed through as-is, so the wall-clock value survives.
    A date without a time gets the project's default start time, or its default finish time when
    end_of_day is set, so "finish 2031-06-05" means the end of that working day.
    """
    dt, has_time = parse_iso(s, field)
    if not has_time:
        if end_of_day:
            t = _default_time(proj, "DefaultFinishTime", datetime.time(17, 0))
        else:
            t = _default_time(proj, "DefaultStartTime", datetime.time(8, 0))
        dt = datetime.datetime.combine(dt.date(), t)
    return dt.replace(tzinfo=_UTC)


def minutes_per_day(proj):
    """Working minutes per day from the project's HoursPerDay (Project has no MinutesPerDay)."""
    try:
        return int(round(float(proj.HoursPerDay) * 60)) or 480
    except Exception:
        return 480


def activate_project(app, proj):
    """
    Make proj the active project. Project.Activate() raises "unexpected error" in an
    invisible (headless) instance, so activate its window instead; that works either way.
    """
    if app.ActiveProject.FullName == proj.FullName:
        return
    try:
        app.WindowActivate(WindowName=proj.Name)
    except Exception:
        proj.Activate()
    if app.ActiveProject.FullName != proj.FullName:
        raise RuntimeError(f"Could not activate project '{proj.Name}'.")


def autosave_enabled():
    """MSPROJECT_AUTOSAVE (default on): save the project after every mutating tool call."""
    return os.environ.get("MSPROJECT_AUTOSAVE", "1").strip().lower() not in ("0", "false", "no", "off")


def commit(app, proj=None):
    """
    Apply the save policy after a mutation. Returns True when the file was saved.

    Untitled projects are never saved here: FileSave on a project with no path opens the
    Backstage Save As page, which blocks the COM object model until a human dismisses it.
    Saving also clears Project's undo stack, so undo_last only works with autosave off.
    """
    active = app.ActiveProject
    proj = proj if proj is not None else active
    if not autosave_enabled() or not proj.Path:
        return False
    if proj.FullName != active.FullName:  # FileSave saves the active project only
        activate_project(app, proj)
        _settle_and_save(app)
        activate_project(app, active)
    else:
        _settle_and_save(app)
    return True


def _settle_and_save(app):
    """
    Finish Project's deferred calculation before saving. Some writes (e.g. a status date)
    defer recalculation to the next read, which would then mark a just-saved file dirty.
    """
    if app.Calculation == -1:  # pjAutomatic; never force a recalc on a user in Manual mode
        app.CalculateProject()
    app.FileSave()


@contextmanager
def batch_calc(app):
    """Suspend automatic calculation for a batch of writes, restore the user's mode, then recalc once."""
    from .calc_policy import deferred_calc
    with deferred_calc(app) as state:
        yield state
    if state.was_deferred:
        app.CalculateProject()


def invoke_positional(com_obj, method, *args):
    """
    Call a COM method with positional arguments, sending None as 'parameter not found'.

    MS Project ignores some arguments when pywin32 passes them by name (FileSaveAs FormatID,
    ProjectSummaryInfo Calendar) and pywin32's typed wrapper rejects placeholders, so this
    goes through IDispatch::Invoke directly, the way VBA/VBScript call these methods.
    """
    import pythoncom
    dispid = com_obj._oleobj_.GetIDsOfNames(method)
    values = [pythoncom.ArgNotFound if a is None else a for a in args]
    return com_obj._oleobj_.Invoke(dispid, 0, pythoncom.DISPATCH_METHOD, True, *values)


def find_resource(proj, name):
    """Find a resource by exact name. Returns the COM Resource or None."""
    for r in proj.Resources:
        if r is not None and r.Name == name:
            return r
    return None


def resolve_resource(proj, name):
    """Find exactly one resource by case-insensitive name. Raises ValueError if missing or ambiguous."""
    matches = [r for r in proj.Resources if r is not None and r.Name.lower() == (name or "").lower()]
    if not matches:
        raise ValueError(f"Resource '{name}' not found. Available: {[r.Name for r in proj.Resources if r is not None]}")
    if len(matches) > 1:
        raise ValueError(f"Resource name '{name}' is ambiguous: {len(matches)} resources share it "
                         f"(UniqueIDs {[r.UniqueID for r in matches]}). Rename one first.")
    return matches[0]


def resolve_calendar(proj, name):
    """Find a base calendar by case-insensitive name. Raises ValueError listing the available ones."""
    names = [c.Name for c in proj.BaseCalendars if c is not None]
    for c in proj.BaseCalendars:
        if c is not None and c.Name.lower() == (name or "").strip().lower():
            return c
    raise ValueError(f"Calendar '{name}' not found. Available: {names}")


def validate_rag(rag):
    """Normalise a RAG value to Red/Amber/Green, or raise ValueError."""
    for value in RAG_VALUES:
        if (rag or "").strip().lower() == value.lower():
            return value
    raise ValueError(f"Invalid rag '{rag}'. Use one of: {', '.join(RAG_VALUES)}.")
