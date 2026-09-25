"""
Drift rules for verify-after-write: how a value re-read from COM is compared with the value
that was written, and why a difference happened (recalculation, constraint, rounding, ...).
"""

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DriftReason(Enum):
    """Why a field value differs from what was requested."""
    NONE = "none"                    # No drift
    RECALCULATION = "recalculation"  # Project recalculated (dates, durations)
    CONSTRAINT = "constraint"        # A constraint overrode the value
    ROUNDING = "rounding"            # Numeric rounding by Project
    NORMALIZATION = "normalization"  # String/enum normalization
    UNKNOWN = "unknown"              # Drifted for unclear reason


# Tolerance thresholds for drift detection
DATE_TOLERANCE = timedelta(days=1)      # ±1 day for scheduling drift
DURATION_TOLERANCE_MINUTES = 60         # ±1 hour for duration rounding
COST_TOLERANCE = 0.01                   # ±1 cent for currency rounding


def _classify_drift(
    field_name: str, requested: Any, actual: Any
) -> tuple[DriftReason, Optional[str]]:
    """
    Determine why a field drifted.

    Returns (reason, detail_string).
    """
    name_lower = field_name.lower()

    # Date fields: check if within scheduling tolerance
    if isinstance(requested, datetime) and isinstance(actual, datetime):
        delta = abs(actual - requested)
        if delta <= DATE_TOLERANCE:
            return (
                DriftReason.RECALCULATION,
                f"Date shifted by {delta}. Within {DATE_TOLERANCE} tolerance "
                f"(likely scheduling recalculation).",
            )
        return (
            DriftReason.RECALCULATION,
            f"Date shifted by {delta}. Exceeds tolerance — "
            f"Project recalculated this date.",
        )

    # Duration fields (usually in minutes from COM)
    if "duration" in name_lower:
        try:
            req_val = float(requested)
            act_val = float(actual)
            delta = abs(act_val - req_val)
            if delta <= DURATION_TOLERANCE_MINUTES:
                return (
                    DriftReason.ROUNDING,
                    f"Duration differs by {delta} min "
                    f"(within {DURATION_TOLERANCE_MINUTES} min tolerance).",
                )
            return (
                DriftReason.RECALCULATION,
                f"Duration changed by {delta} min — "
                f"Project recalculated based on assignments/calendar.",
            )
        except (ValueError, TypeError):
            pass

    # Cost fields
    if "cost" in name_lower or "rate" in name_lower:
        try:
            req_val = float(requested)
            act_val = float(actual)
            if abs(act_val - req_val) <= COST_TOLERANCE:
                return (
                    DriftReason.ROUNDING,
                    f"Cost differs by {abs(act_val - req_val):.4f} "
                    f"(within rounding tolerance).",
                )
        except (ValueError, TypeError):
            pass

    # String normalization (e.g., "Yes" -> "Yes", trimmed whitespace)
    if isinstance(requested, str) and isinstance(actual, str):
        if requested.strip().lower() == actual.strip().lower():
            return (
                DriftReason.NORMALIZATION,
                "String normalized (case or whitespace).",
            )

    # Constraint-related fields
    if "constraint" in name_lower:
        return (
            DriftReason.CONSTRAINT,
            f"Value changed from '{requested}' to '{actual}' — "
            f"a constraint may have overridden this field.",
        )

    logger.warning(
        "Unknown drift: field=%s requested=%r (%s) actual=%r (%s)",
        field_name, requested, type(requested).__name__,
        actual, type(actual).__name__,
    )
    return (DriftReason.UNKNOWN, f"Changed from '{requested}' to '{actual}'.")


def _values_match(
    field_name: str, requested: Any, actual: Any
) -> bool:
    """
    Check if requested and actual values match, with type-aware tolerance.
    """
    if requested is None and actual is None:
        return True
    if requested is None or actual is None:
        return False

    # Exact match
    if requested == actual:
        return True

    # Date tolerance
    if isinstance(requested, datetime) and isinstance(actual, datetime):
        return abs(actual - requested) <= DATE_TOLERANCE

    # Numeric tolerance for durations and costs
    name_lower = field_name.lower()
    if "duration" in name_lower:
        try:
            return abs(float(actual) - float(requested)) <= DURATION_TOLERANCE_MINUTES
        except (ValueError, TypeError):
            pass

    if "cost" in name_lower or "rate" in name_lower:
        try:
            return abs(float(actual) - float(requested)) <= COST_TOLERANCE
        except (ValueError, TypeError):
            pass

    # String comparison (case-insensitive, trimmed)
    if isinstance(requested, str) and isinstance(actual, str):
        return requested.strip().lower() == actual.strip().lower()

    return False
