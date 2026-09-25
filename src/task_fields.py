"""
Task field validation and writing shared by update_task, bulk_update_tasks and dry_run_bulk_update.

validate_changes rejects unknown keys, out-of-range values and invalid RAG / task types before
anything is written; apply_changes writes in a safe order and reports any value MS Project adjusted.
"""

from .com_helpers import _get_mpd
from .com_write import to_com_date, validate_rag

TASK_TYPES = {"fixedunits": 0, "fixedduration": 1, "fixedwork": 2}
FIELD_ATTR = {
    "name": "Name", "percent_complete": "PercentComplete", "notes": "Notes", "manual": "Manual",
    "rag": "Text1", "text2": "Text2", "text3": "Text3", "flag1": "Flag1", "flag2": "Flag2",
    "priority": "Priority", "task_type": "Type", "start": "Start", "finish": "Finish",
}
UPDATABLE = tuple(FIELD_ATTR) + ("duration_days",)
# Names reported in "changed", kept identical to what update_task has always returned.
CHANGED_NAMES = {"task_type": "type", "rag": "rag/text1"}
# Applied in this order: mode and type first so Project schedules the date writes correctly.
WRITE_ORDER = ("manual", "task_type", "duration_days", "start", "finish", "name", "percent_complete",
               "priority", "rag", "text2", "text3", "notes", "flag1", "flag2")
SAFE_URL_SCHEMES = ("http", "https", "mailto", "file", "ftp", "")


def _int_in(value, field, low, high):
    number = int(value)
    if not low <= number <= high:
        raise ValueError(f"{field} must be between {low} and {high} (got {value}).")
    return number


def validate_changes(proj, changes):
    """Validate and normalise {field: value}. None means 'leave unchanged'. Raises ValueError."""
    unknown = [k for k in changes if k not in UPDATABLE]
    if unknown:
        raise ValueError(f"Unknown field(s) {unknown}. Updatable fields: {', '.join(UPDATABLE)}.")
    out = {}
    for key, value in changes.items():
        if value is None:
            continue
        if key == "name":
            if not str(value).strip():
                raise ValueError("name cannot be empty.")
            out[key] = str(value)
        elif key == "percent_complete":
            out[key] = _int_in(value, key, 0, 100)
        elif key == "priority":
            out[key] = _int_in(value, key, 0, 1000)
        elif key == "duration_days":
            if float(value) < 0:
                raise ValueError("duration_days cannot be negative.")
            out[key] = float(value)
        elif key in ("start", "finish"):
            out[key] = to_com_date(proj, value, end_of_day=(key == "finish"), field=key)
        elif key == "rag":
            out[key] = validate_rag(value) if str(value).strip() else ""
        elif key == "task_type":
            if str(value).lower() not in TASK_TYPES:
                raise ValueError(f"Invalid task_type '{value}'. Use FixedUnits, FixedDuration, or FixedWork.")
            out[key] = TASK_TYPES[str(value).lower()]
        elif key in ("manual", "flag1", "flag2"):
            out[key] = bool(value)
        else:
            out[key] = str(value)  # notes/text2/text3: "" clears the field
    if "start" in out and "finish" in out and out["finish"] < out["start"]:
        raise ValueError("finish is before start.")
    return out


def apply_changes(proj, t, values):
    """Write validated values in a safe order. Returns (changed, warnings)."""
    changed, warnings = [], []
    for key in WRITE_ORDER:
        if key not in values:
            continue
        if key == "duration_days":
            t.Duration = round(values[key] * _get_mpd(proj))
        else:
            setattr(t, FIELD_ATTR[key], values[key])
        changed.append(CHANGED_NAMES.get(key, key))
    for key in ("start", "finish"):
        if key in values:
            actual = str(getattr(t, FIELD_ATTR[key]))[:16]
            wanted = values[key].strftime("%Y-%m-%d %H:%M")
            if actual != wanted:
                warnings.append(f"MS Project scheduled {key} at {actual}, not {wanted} "
                                "(auto-scheduling, constraints or calendar).")
    return changed, warnings
