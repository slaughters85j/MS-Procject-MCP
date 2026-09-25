"""
Converters from mpxj ProjectCalendar and ProjectProperties objects to plain dicts.
"""

from typing import Any, Dict

from .mpxj_values import _safe_set, _safe_set_bool, _safe_set_date, _safe_set_number


# ---------------------------------------------------------------------------
# Calendar extraction
# ---------------------------------------------------------------------------

def _calendar_to_dict(calendar) -> Dict[str, Any]:
    """Convert an mpxj ProjectCalendar to a plain dict."""
    result = {}

    _safe_set(result, "unique_id", calendar, "getUniqueID")
    _safe_set(result, "name", calendar, "getName")

    # Base calendar
    try:
        parent = calendar.getParent()
        if parent and parent.getName():
            result["base_calendar"] = str(parent.getName())
    except Exception:
        pass

    # Working days
    try:
        from java.time import DayOfWeek
        days, hours = {}, {}
        for dow in DayOfWeek.values():
            try:
                day_type = calendar.getCalendarDayType(dow)
                days[str(dow)] = str(day_type) if day_type else "DEFAULT"
                ranges = calendar.getCalendarHours(dow)
                if ranges is not None and ranges.size() > 0:
                    hours[str(dow)] = [f"{r.getStart()}-{r.getEnd()}" for r in ranges]
            except Exception:
                pass
        if days:
            result["working_days"] = days
        if hours:
            result["working_hours"] = hours
    except Exception:
        pass

    # Exceptions
    try:
        exceptions = calendar.getCalendarExceptions()
        if exceptions and exceptions.size() > 0:
            exc_list = []
            for i in range(exceptions.size()):
                exc = exceptions.get(i)
                exc_dict = {}
                _safe_set(exc_dict, "name", exc, "getName")
                _safe_set_date(exc_dict, "from_date", exc, "getFromDate")
                _safe_set_date(exc_dict, "to_date", exc, "getToDate")
                _safe_set_bool(exc_dict, "working", exc, "getWorking")
                if exc_dict:
                    exc_list.append(exc_dict)
            if exc_list:
                result["exceptions"] = exc_list
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Project properties extraction
# ---------------------------------------------------------------------------

def _project_properties_to_dict(properties) -> Dict[str, Any]:
    """Extract project-level properties to a dict."""
    result = {}

    _safe_set(result, "project_title", properties, "getProjectTitle")
    _safe_set(result, "subject", properties, "getSubject")
    _safe_set(result, "author", properties, "getAuthor")
    _safe_set(result, "manager", properties, "getManager")
    _safe_set(result, "company", properties, "getCompany")
    _safe_set(result, "category", properties, "getCategory")
    _safe_set(result, "comments", properties, "getComments")

    _safe_set_date(result, "start_date", properties, "getStartDate")
    _safe_set_date(result, "finish_date", properties, "getFinishDate")
    _safe_set_date(result, "current_date", properties, "getCurrentDate")
    _safe_set_date(result, "status_date", properties, "getStatusDate")
    _safe_set_date(result, "creation_date", properties, "getCreationDate")
    _safe_set_date(result, "last_saved", properties, "getLastSaved")

    _safe_set(result, "schedule_from", properties, "getScheduleFrom")
    _safe_set_number(result, "minutes_per_day", properties, "getMinutesPerDay")
    _safe_set_number(result, "minutes_per_week", properties, "getMinutesPerWeek")
    _safe_set_number(result, "days_per_month", properties, "getDaysPerMonth")

    _safe_set(result, "default_calendar_name", properties, "getDefaultCalendarName")
    _safe_set(result, "currency_symbol", properties, "getCurrencySymbol")

    return result
