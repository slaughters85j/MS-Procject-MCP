"""
Converters from mpxj Task, Resource, and ResourceAssignment objects to plain dicts.
Calendars and project properties are in mpxj_project_convert.
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
                    pred = rel.getPredecessorTask()  # MPXJ 13+; getTargetTask() was removed
                    if pred:
                        pred_info["task_unique_id"] = _java_to_python(pred.getUniqueID())
                        pred_info["task_name"] = str(pred.getName()) if pred.getName() else None
                except Exception:
                    pass
                _safe_set(pred_info, "type", rel, "getType", str)  # FS/SS/FF/SF, as the COM tools use
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

def _resource_totals(resource, props) -> Dict[str, Any]:
    """
    Work and cost totals summed from the resource's assignments, as Project computes them.
    Project does not store these rollups in the .mpp, so mpxj reads them as 0. props (the
    ProjectProperties) converts every work value to hours. Returns {} when they cannot be
    computed (the per-field reads then stand).
    """
    if props is None:
        return {}
    try:
        import jpype
        hours = jpype.JClass("org.mpxj.TimeUnit").HOURS
        assignments = list(resource.getTaskAssignments())
        totals = {}
        for key, getter in (("work", "getWork"), ("actual_work", "getActualWork"),
                            ("remaining_work", "getRemainingWork")):
            durations = [getattr(a, getter)() for a in assignments]
            amount = sum(float(d.convertUnits(hours, props).getDuration()) for d in durations if d is not None)
            totals[key] = {"amount": amount, "units": str(hours)}
        for key, getter in (("cost", "getCost"), ("actual_cost", "getActualCost")):
            values = [getattr(a, getter)() for a in assignments]
            totals[key] = _java_to_python(sum(float(v) for v in values if v is not None))
        return totals
    except Exception:
        return {}


def _resource_to_dict(resource, props=None) -> Dict[str, Any]:
    """Convert an mpxj Resource object to a plain dict; with props, work and cost are the
    totals of its assignments."""
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

    result.update(_resource_totals(resource, props))

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
