"""
Converters from mpxj Task, Resource, ResourceAssignment, ProjectCalendar, and
ProjectProperties objects to plain dicts.
"""

from typing import Any, Dict

from .mpxj_values import (
    _java_to_python, _safe_set, _safe_set_bool, _safe_set_date, _safe_set_duration,
    _safe_set_enum, _safe_set_number,
)


# ---------------------------------------------------------------------------
# Task extraction
# ---------------------------------------------------------------------------

def _task_to_dict(task) -> Dict[str, Any]:
    """Convert an mpxj Task object to a plain dict."""
    result = {}

    # Identity fields
    _safe_set(result, "unique_id", task, "getUniqueID")
    _safe_set(result, "id", task, "getID")
    _safe_set(result, "name", task, "getName")

    # Hierarchy
    _safe_set(result, "outline_level", task, "getOutlineLevel")
    _safe_set(result, "outline_number", task, "getOutlineNumber")
    _safe_set(result, "wbs", task, "getWBS")
    _safe_set_bool(result, "summary", task, "getSummary")

    # Schedule
    _safe_set_date(result, "start", task, "getStart")
    _safe_set_date(result, "finish", task, "getFinish")
    _safe_set_duration(result, "duration", task, "getDuration")
    _safe_set_date(result, "actual_start", task, "getActualStart")
    _safe_set_date(result, "actual_finish", task, "getActualFinish")
    _safe_set_date(result, "baseline_start", task, "getBaselineStart")
    _safe_set_date(result, "baseline_finish", task, "getBaselineFinish")
    _safe_set_duration(result, "baseline_duration", task, "getBaselineDuration")

    # Progress
    _safe_set_number(result, "percent_complete", task, "getPercentageComplete")
    _safe_set_number(result, "physical_percent_complete", task, "getPhysicalPercentComplete")

    # Constraints
    _safe_set_enum(result, "constraint_type", task, "getConstraintType")
    _safe_set_date(result, "constraint_date", task, "getConstraintDate")
    _safe_set_date(result, "deadline", task, "getDeadline")

    # Priority and type
    _safe_set_enum(result, "priority", task, "getPriority")
    _safe_set_enum(result, "type", task, "getType")
    _safe_set_bool(result, "milestone", task, "getMilestone")
    _safe_set_bool(result, "critical", task, "getCritical")
    _safe_set_bool(result, "active", task, "getActive")

    # Slack
    _safe_set_duration(result, "total_slack", task, "getTotalSlack")
    _safe_set_duration(result, "free_slack", task, "getFreeSlack")

    # Cost / work
    _safe_set_number(result, "cost", task, "getCost")
    _safe_set_number(result, "actual_cost", task, "getActualCost")
    _safe_set_number(result, "baseline_cost", task, "getBaselineCost")
    _safe_set_duration(result, "work", task, "getWork")
    _safe_set_duration(result, "actual_work", task, "getActualWork")
    _safe_set_duration(result, "remaining_work", task, "getRemainingWork")

    # Notes
    _safe_set(result, "notes", task, "getNotes")

    # Calendar
    try:
        cal = task.getCalendar()
        if cal is not None:
            result["calendar_name"] = str(cal.getName()) if cal.getName() else None
    except Exception:
        pass

    # Predecessors
    try:
        preds = task.getPredecessors()
        if preds is not None and preds.size() > 0:
            pred_list = []
            for i in range(preds.size()):
                rel = preds.get(i)
                pred_info = {}
                try:
                    target = rel.getTargetTask()
                    if target:
                        pred_info["task_unique_id"] = _java_to_python(target.getUniqueID())
                        pred_info["task_name"] = str(target.getName()) if target.getName() else None
                except Exception:
                    pass
                _safe_set_enum(pred_info, "type", rel, "getType")
                _safe_set_duration(pred_info, "lag", rel, "getLag")
                if pred_info:
                    pred_list.append(pred_info)
            if pred_list:
                result["predecessors"] = pred_list
    except Exception:
        pass

    # Resource assignments (names only — full assignments via read_assignments)
    try:
        assignments = task.getResourceAssignments()
        if assignments is not None and assignments.size() > 0:
            resource_names = []
            for i in range(assignments.size()):
                asn = assignments.get(i)
                res = asn.getResource()
                if res and res.getName():
                    resource_names.append(str(res.getName()))
            if resource_names:
                result["resource_names"] = resource_names
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Resource extraction
# ---------------------------------------------------------------------------

def _resource_to_dict(resource) -> Dict[str, Any]:
    """Convert an mpxj Resource object to a plain dict."""
    result = {}

    _safe_set(result, "unique_id", resource, "getUniqueID")
    _safe_set(result, "id", resource, "getID")
    _safe_set(result, "name", resource, "getName")

    _safe_set_enum(result, "type", resource, "getType")
    _safe_set(result, "initials", resource, "getInitials")
    _safe_set(result, "group", resource, "getGroup")
    _safe_set(result, "email_address", resource, "getEmailAddress")
    _safe_set_number(result, "max_units", resource, "getMaxUnits")

    _safe_set_number(result, "standard_rate", resource, "getStandardRate")
    _safe_set_number(result, "overtime_rate", resource, "getOvertimeRate")
    _safe_set_number(result, "cost_per_use", resource, "getCostPerUse")
    _safe_set_number(result, "cost", resource, "getCost")
    _safe_set_number(result, "actual_cost", resource, "getActualCost")

    _safe_set_duration(result, "work", resource, "getWork")
    _safe_set_duration(result, "actual_work", resource, "getActualWork")
    _safe_set_duration(result, "remaining_work", resource, "getRemainingWork")

    _safe_set_date(result, "available_from", resource, "getAvailableFrom")
    _safe_set_date(result, "available_to", resource, "getAvailableTo")

    _safe_set(result, "notes", resource, "getNotes")

    # Calendar
    try:
        cal = resource.getCalendar()
        if cal is not None:
            result["calendar_name"] = str(cal.getName()) if cal.getName() else None
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Assignment extraction
# ---------------------------------------------------------------------------

def _assignment_to_dict(assignment) -> Dict[str, Any]:
    """Convert an mpxj ResourceAssignment to a plain dict."""
    result = {}

    _safe_set(result, "unique_id", assignment, "getUniqueID")

    # Task info
    try:
        task = assignment.getTask()
        if task:
            result["task_unique_id"] = _java_to_python(task.getUniqueID())
            result["task_name"] = str(task.getName()) if task.getName() else None
    except Exception:
        pass

    # Resource info
    try:
        resource = assignment.getResource()
        if resource:
            result["resource_unique_id"] = _java_to_python(resource.getUniqueID())
            result["resource_name"] = str(resource.getName()) if resource.getName() else None
    except Exception:
        pass

    _safe_set_number(result, "units", assignment, "getUnits")
    _safe_set_duration(result, "work", assignment, "getWork")
    _safe_set_duration(result, "actual_work", assignment, "getActualWork")
    _safe_set_duration(result, "remaining_work", assignment, "getRemainingWork")
    _safe_set_number(result, "cost", assignment, "getCost")
    _safe_set_number(result, "actual_cost", assignment, "getActualCost")
    _safe_set_date(result, "start", assignment, "getStart")
    _safe_set_date(result, "finish", assignment, "getFinish")
    _safe_set_number(result, "percent_work_complete", assignment, "getPercentageWorkComplete")

    return result


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
        days = {}
        for dow in DayOfWeek.values():
            try:
                day_type = calendar.getCalendarDayType(dow)
                days[str(dow)] = str(day_type) if day_type else "DEFAULT"
            except Exception:
                pass
        if days:
            result["working_days"] = days
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
