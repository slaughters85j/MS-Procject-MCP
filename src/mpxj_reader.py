"""
Sprint 4, Item #11: Fast read path via mpxj/jpype.

Reads .mpp files from DISK (the SAVED file) without COM automation.
Cross-platform: works on Mac, Linux, Windows — no MS Project installation needed.

Uses the mpxj Python package (which uses jpype1 for JVM interop).
Measured: 1.6s vs 30-48s on 8,000+ task schedules via COM.

IMPORTANT: This reads the SAVED .mpp file, NOT the live COM state.
Unsaved changes in MS Project are NOT reflected. For live state, use
the COM-based tools (get_tasks, get_resources, etc.).

JVM lifecycle:
  - Started lazily on first read, kept alive for the process lifetime.
  - jpype1 does not support JVM restart after shutdown, so we never shut it down.
  - Thread-safe: jpype1 handles GIL/JVM interop internally.
"""

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "is_mpxj_available",
    "read_tasks",
    "read_resources",
    "read_assignments",
    "read_calendars",
    "read_project_info",
    "MpxjError",
    "MpxjNotAvailableError",
    "MpxjFileError",
    "MpxjParseError",
]

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MpxjError(Exception):
    """Base exception for mpxj reader errors."""
    pass


class MpxjNotAvailableError(MpxjError):
    """mpxj or jpype1 is not installed."""
    pass


class MpxjFileError(MpxjError):
    """File not found, not readable, or not a valid .mpp file."""
    pass


class MpxjParseError(MpxjError):
    """mpxj failed to parse the .mpp file."""
    pass


# ---------------------------------------------------------------------------
# JVM lifecycle
# ---------------------------------------------------------------------------

_jvm_started = False  # Best-effort fast path; jpype.startJVM() is internally synchronized.


def _ensure_jvm() -> None:
    """Start the JVM if not already running. No-op after first call."""
    global _jvm_started
    if _jvm_started:
        return

    try:
        import jpype
    except ImportError:
        raise MpxjNotAvailableError(
            "jpype1 is not installed. Install with: "
            "pip install 'msproject-mcp[mpxj]'"
        )

    if not jpype.isJVMStarted():
        try:
            # mpxj bundles its own JARs; jpype finds the default JVM
            import mpxj  # noqa: F401 — import triggers JAR registration
            jpype.startJVM()
            logger.info("JVM started for mpxj fast-read path.")
        except Exception as exc:
            raise MpxjNotAvailableError(
                f"Failed to start JVM for mpxj: {exc}. "
                f"Ensure a JDK/JRE is installed and JAVA_HOME is set."
            ) from exc

    _jvm_started = True


def is_mpxj_available() -> bool:
    """Check whether mpxj and jpype1 are importable (does NOT start JVM)."""
    try:
        import mpxj  # noqa: F401
        import jpype  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# File validation
# ---------------------------------------------------------------------------

_VALID_EXTENSIONS = frozenset((".mpp", ".mpt", ".mpx", ".xml", ".mspdi"))


def _validate_file(file_path: str) -> str:
    """Validate the file exists, is readable, and has a supported extension.

    Returns the resolved absolute path.
    Raises MpxjFileError with a descriptive message on any problem.
    """
    if not file_path or not file_path.strip():
        raise MpxjFileError("file_path is required — provide the path to a .mpp file.")

    resolved = os.path.abspath(file_path)

    if not os.path.exists(resolved):
        raise MpxjFileError(
            f"File not found: {file_path!r}. "
            f"The mpxj tools read the SAVED .mpp file from disk. "
            f"Ensure the file exists and the path is correct."
        )

    if not os.path.isfile(resolved):
        raise MpxjFileError(f"Not a file: {file_path!r} (is it a directory?).")

    if not os.access(resolved, os.R_OK):
        raise MpxjFileError(f"File not readable: {file_path!r}. Check permissions.")

    ext = os.path.splitext(resolved)[1].lower()
    if ext not in _VALID_EXTENSIONS:
        raise MpxjFileError(
            f"Unsupported file extension {ext!r}. "
            f"Supported: {', '.join(sorted(_VALID_EXTENSIONS))}"
        )

    return resolved


# ---------------------------------------------------------------------------
# Date formatting helper
# ---------------------------------------------------------------------------

def _format_java_date(java_date) -> Optional[str]:
    """Convert a Java LocalDateTime/LocalDate to ISO-8601 string, or None."""
    if java_date is None:
        return None
    try:
        return str(java_date)
    except Exception:
        return None


def _format_duration(duration) -> Optional[Dict[str, Any]]:
    """Convert an mpxj Duration to a dict with amount and units."""
    if duration is None:
        return None
    try:
        return {
            "amount": float(duration.getDuration()),
            "units": str(duration.getUnits()),
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Core reader: open project file
# ---------------------------------------------------------------------------

def _open_project(file_path: str):
    """Open an .mpp file and return the mpxj ProjectFile object.

    Raises MpxjParseError on parse failure.
    """
    _ensure_jvm()

    try:
        from net.sf.mpxj.reader import UniversalProjectReader
    except ImportError:
        # Fallback: mpxj Python wrapper
        try:
            import mpxj as mpxj_pkg
            reader = mpxj_pkg.ProjectReader()
            return reader.read(file_path)
        except Exception as exc:
            raise MpxjParseError(
                f"Failed to parse {file_path!r}: {exc}. "
                f"The file may be corrupted or in an unsupported format."
            ) from exc

    try:
        reader = UniversalProjectReader()
        project = reader.read(file_path)
        if project is None:
            raise MpxjParseError(
                f"mpxj returned None for {file_path!r}. "
                f"The file may be empty, corrupted, or not a valid project file."
            )
        return project
    except MpxjParseError:
        raise
    except Exception as exc:
        raise MpxjParseError(
            f"Failed to parse {file_path!r}: {exc}. "
            f"The file may be corrupted or in an unsupported format."
        ) from exc


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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read_tasks(file_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Read all tasks from a .mpp file.

    Returns (tasks_list, source_metadata).
    source_metadata includes file path, read timestamp, and task count.
    """
    resolved = _validate_file(file_path)
    project = _open_project(resolved)

    tasks = []
    try:
        all_tasks = project.getTasks()
        for i in range(all_tasks.size()):
            task = all_tasks.get(i)
            # Skip the project summary task (ID 0) — it's a container, not a real task
            task_id = _java_to_python(task.getID())
            if task_id == 0:
                continue
            tasks.append(_task_to_dict(task))
    except Exception as exc:
        raise MpxjParseError(
            f"Failed to extract tasks from {file_path!r}: {exc}"
        ) from exc

    source = _source_metadata(resolved, "tasks", len(tasks))
    return tasks, source


def read_resources(file_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Read all resources from a .mpp file.

    Returns (resources_list, source_metadata).
    """
    resolved = _validate_file(file_path)
    project = _open_project(resolved)

    resources = []
    try:
        all_resources = project.getResources()
        for i in range(all_resources.size()):
            resource = all_resources.get(i)
            # Skip the dummy resource (ID 0)
            res_id = _java_to_python(resource.getID())
            if res_id == 0:
                continue
            resources.append(_resource_to_dict(resource))
    except Exception as exc:
        raise MpxjParseError(
            f"Failed to extract resources from {file_path!r}: {exc}"
        ) from exc

    source = _source_metadata(resolved, "resources", len(resources))
    return resources, source


def read_assignments(file_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Read all resource assignments from a .mpp file.

    Returns (assignments_list, source_metadata).
    """
    resolved = _validate_file(file_path)
    project = _open_project(resolved)

    assignments = []
    try:
        all_assignments = project.getResourceAssignments()
        for i in range(all_assignments.size()):
            asn = all_assignments.get(i)
            assignments.append(_assignment_to_dict(asn))
    except Exception as exc:
        raise MpxjParseError(
            f"Failed to extract assignments from {file_path!r}: {exc}"
        ) from exc

    source = _source_metadata(resolved, "assignments", len(assignments))
    return assignments, source


def read_calendars(file_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Read all calendars from a .mpp file.

    Returns (calendars_list, source_metadata).
    """
    resolved = _validate_file(file_path)
    project = _open_project(resolved)

    calendars = []
    try:
        all_calendars = project.getCalendars()
        for i in range(all_calendars.size()):
            cal = all_calendars.get(i)
            calendars.append(_calendar_to_dict(cal))
    except Exception as exc:
        raise MpxjParseError(
            f"Failed to extract calendars from {file_path!r}: {exc}"
        ) from exc

    source = _source_metadata(resolved, "calendars", len(calendars))
    return calendars, source


def read_project_info(file_path: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Read project-level properties from a .mpp file.

    Returns (properties_dict, source_metadata).
    """
    resolved = _validate_file(file_path)
    project = _open_project(resolved)

    try:
        properties = project.getProjectProperties()
        info = _project_properties_to_dict(properties)
    except Exception as exc:
        raise MpxjParseError(
            f"Failed to extract project properties from {file_path!r}: {exc}"
        ) from exc

    # Also add summary counts
    try:
        info["task_count"] = project.getTasks().size()
    except Exception:
        pass
    try:
        info["resource_count"] = project.getResources().size()
    except Exception:
        pass
    try:
        info["assignment_count"] = project.getResourceAssignments().size()
    except Exception:
        pass
    try:
        info["calendar_count"] = project.getCalendars().size()
    except Exception:
        pass

    source = _source_metadata(resolved, "project_info", 1)
    return info, source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _java_to_python(value) -> Any:
    """Convert a Java boxed type (Integer, Double, etc.) to a Python native."""
    if value is None:
        return None
    try:
        # jpype boxed types have .value or can be cast
        return value.intValue() if hasattr(value, 'intValue') else int(value)
    except (TypeError, ValueError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return str(value)


def _safe_set(result: dict, key: str, obj, getter_name: str) -> None:
    """Safely call a getter and store the result if non-None."""
    try:
        getter = getattr(obj, getter_name, None)
        if getter is None:
            return
        value = getter()
        if value is not None:
            result[key] = _java_to_python(value) if not isinstance(value, str) else str(value)
    except Exception:
        pass


def _safe_set_date(result: dict, key: str, obj, getter_name: str) -> None:
    """Safely call a date getter and format to ISO string."""
    try:
        getter = getattr(obj, getter_name, None)
        if getter is None:
            return
        value = getter()
        formatted = _format_java_date(value)
        if formatted:
            result[key] = formatted
    except Exception:
        pass


def _safe_set_duration(result: dict, key: str, obj, getter_name: str) -> None:
    """Safely call a duration getter and format to dict."""
    try:
        getter = getattr(obj, getter_name, None)
        if getter is None:
            return
        value = getter()
        formatted = _format_duration(value)
        if formatted:
            result[key] = formatted
    except Exception:
        pass


def _safe_set_number(result: dict, key: str, obj, getter_name: str) -> None:
    """Safely call a numeric getter and store the value."""
    try:
        getter = getattr(obj, getter_name, None)
        if getter is None:
            return
        value = getter()
        if value is not None:
            result[key] = _java_to_python(value)
    except Exception:
        pass


def _safe_set_bool(result: dict, key: str, obj, getter_name: str) -> None:
    """Safely call a boolean getter and store the value."""
    try:
        getter = getattr(obj, getter_name, None)
        if getter is None:
            return
        value = getter()
        if value is not None:
            result[key] = bool(value)
    except Exception:
        pass


def _safe_set_enum(result: dict, key: str, obj, getter_name: str) -> None:
    """Safely call an enum getter and store as string."""
    try:
        getter = getattr(obj, getter_name, None)
        if getter is None:
            return
        value = getter()
        if value is not None:
            result[key] = str(value)
    except Exception:
        pass


def _source_metadata(
    file_path: str,
    entity_type: str,
    count: int,
) -> Dict[str, Any]:
    """Build the source metadata block included in every mpxj response."""
    return {
        "backend": "mpxj",
        "file_path": file_path,
        "entity_type": entity_type,
        "count": count,
        "read_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Data read from SAVED .mpp file on disk. "
            "Unsaved changes in MS Project are NOT reflected."
        ),
    }
