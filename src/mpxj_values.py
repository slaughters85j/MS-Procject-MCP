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
