"""
Fast read path via mpxj/jpype: the public read_* API.

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

The JVM and file plumbing live in mpxj_jvm, value conversion in mpxj_values, and the
object-to-dict converters in mpxj_convert.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from .mpxj_convert import _assignment_to_dict, _resource_to_dict, _task_to_dict
from .mpxj_project_convert import _calendar_to_dict, _project_properties_to_dict
from .mpxj_jvm import (
    MpxjError, MpxjFileError, MpxjNotAvailableError, MpxjParseError, _open_project,
    _validate_file, is_mpxj_available,
)
from .mpxj_values import _java_to_python

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
# What Project itself lists
# ---------------------------------------------------------------------------

def _listed_tasks(project) -> list:
    """Tasks without the project summary task (ID 0), which is a container, not a task."""
    return [t for t in project.getTasks() if _java_to_python(t.getID()) != 0]


def _listed_resources(project) -> list:
    """Resources without the blank resource (ID 0) that every .mpp carries."""
    return [r for r in project.getResources() if _java_to_python(r.getID()) != 0]


def _listed_assignments(project) -> list:
    """Assignments that have a resource. The .mpp also stores a resource-less placeholder
    for every task, which Project never shows as an assignment."""
    return [a for a in project.getResourceAssignments() if a.getResource() is not None]


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

    try:
        tasks = [_task_to_dict(t) for t in _listed_tasks(project)]
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

    try:
        props = project.getProjectProperties()
        resources = [_resource_to_dict(r, props) for r in _listed_resources(project)]
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

    try:
        assignments = [_assignment_to_dict(a) for a in _listed_assignments(project)]
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

    try:
        calendars = [_calendar_to_dict(c) for c in project.getCalendars()]
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

    # Summary counts, matching what read_tasks/read_resources/... return
    for key, listed in (("task_count", _listed_tasks), ("resource_count", _listed_resources),
                        ("assignment_count", _listed_assignments),
                        ("calendar_count", lambda p: list(p.getCalendars()))):
        try:
            info[key] = len(listed(project))
        except Exception:
            pass

    source = _source_metadata(resolved, "project_info", 1)
    return info, source


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
