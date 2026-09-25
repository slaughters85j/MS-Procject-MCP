"""
Conversions from mpxj Java values to JSON-friendly Python values, and the _safe_set_*
helpers that write a converted field into a dict only when the read succeeds.
"""

from typing import Any, Dict, Optional


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
# Helpers
# ---------------------------------------------------------------------------

def _number(value) -> Any:
    """A number as int when it is whole, float otherwise (costs, rates and units keep decimals)."""
    number = float(value)
    return int(number) if number.is_integer() else number


def _java_to_python(value) -> Any:
    """
    Convert an mpxj/Java value to a JSON-friendly Python value. jpype boxes Integer as int and
    Double as float; mpxj enums (ScheduleFrom, ...) print their numeric code, so use name();
    Priority carries getValue(); a Rate becomes {"amount", "units"}.
    """
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float)):
        return _number(value)
    if hasattr(value, "name") and hasattr(value, "ordinal"):
        return str(value.name())
    if hasattr(value, "getAmount") and hasattr(value, "getUnits"):
        return {"amount": _number(value.getAmount()), "units": str(value.getUnits())}
    if hasattr(value, "getValue"):
        return _java_to_python(value.getValue())
    if hasattr(value, "doubleValue"):  # any other java.lang.Number
        return _number(value.doubleValue())
    return str(value)  # java.lang.String and anything else


def _safe_set(result: dict, key: str, obj, getter_name: str, convert=_java_to_python) -> None:
    """Call obj.getter_name(), convert the value, and store it under key unless it is None.
    A missing getter or a failing read leaves the key out."""
    try:
        getter = getattr(obj, getter_name, None)
        if getter is None:
            return
        value = getter()
        if value is not None:
            value = convert(value)
        if value is not None:
            result[key] = value
    except Exception:
        pass


def _safe_set_date(result: dict, key: str, obj, getter_name: str) -> None:
    """_safe_set for a Java date, stored as an ISO-8601 string."""
    _safe_set(result, key, obj, getter_name, _format_java_date)


def _safe_set_duration(result: dict, key: str, obj, getter_name: str) -> None:
    """_safe_set for an mpxj Duration, stored as {"amount", "units"}."""
    _safe_set(result, key, obj, getter_name, _format_duration)


def _safe_set_bool(result: dict, key: str, obj, getter_name: str) -> None:
    """_safe_set for a boolean flag."""
    _safe_set(result, key, obj, getter_name, bool)


# Numbers, enums, Priority and Rate all go through _java_to_python.
_safe_set_number = _safe_set_enum = _safe_set
