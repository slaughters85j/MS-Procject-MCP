"""
Verify-After-Write

After every mutation, re-read the fields you think you set and return
{requested, actual, drifted}. Project will lie to you via recalculation.

This module provides:
- verify_fields(): compare requested vs actual values with tolerances
- FieldResult: per-field verification result
- VerifyResult: aggregate verification payload
- Drift detection with reason classification

NOTE: Testing against live MS Project remains required.
"""

import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

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


@dataclass
class FieldResult:
    """Verification result for a single field."""
    field_name: str
    requested: Any
    actual: Any
    matched: bool
    drifted: bool = False
    drift_reason: str = DriftReason.NONE.value
    drift_detail: Optional[str] = None
    error: Optional[str] = None  # Non-None if the read itself failed

    def to_dict(self) -> dict:
        d = asdict(self)
        # Stringify datetimes for JSON serialization
        for key in ("requested", "actual"):
            if isinstance(d[key], datetime):
                d[key] = d[key].isoformat()
        return d


@dataclass
class VerifyResult:
    """Aggregate verification payload for a mutation."""
    success: bool                      # All fields matched (within tolerance)
    field_count: int = 0
    matched_count: int = 0
    drifted_count: int = 0
    fields: List[FieldResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "field_count": self.field_count,
            "matched_count": self.matched_count,
            "drifted_count": self.drifted_count,
            "fields": [f.to_dict() for f in self.fields],
        }

    @property
    def drifted_fields(self) -> List[FieldResult]:
        return [f for f in self.fields if f.drifted]


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


def verify_fields(
    requested: Dict[str, Any],
    actual: Dict[str, Any],
) -> VerifyResult:
    """
    Compare requested field values against actual post-write values.

    Args:
        requested: Dict of {field_name: value_we_tried_to_set}
        actual: Dict of {field_name: value_project_actually_has}

    Returns:
        VerifyResult with per-field breakdown and drift classification.
    """
    results = []

    for field_name, req_value in requested.items():
        act_value = actual.get(field_name)
        matched = _values_match(field_name, req_value, act_value)

        if matched:
            results.append(FieldResult(
                field_name=field_name,
                requested=req_value,
                actual=act_value,
                matched=True,
            ))
        else:
            reason, detail = _classify_drift(field_name, req_value, act_value)
            results.append(FieldResult(
                field_name=field_name,
                requested=req_value,
                actual=act_value,
                matched=False,
                drifted=True,
                drift_reason=reason.value,
                drift_detail=detail,
            ))

    matched_count = sum(1 for r in results if r.matched)
    drifted_count = sum(1 for r in results if r.drifted)

    return VerifyResult(
        success=(drifted_count == 0),
        field_count=len(results),
        matched_count=matched_count,
        drifted_count=drifted_count,
        fields=results,
    )


def read_task_fields(
    task, field_names: List[str]
) -> tuple[Dict[str, Any], Dict[str, str]]:
    """
    Read field values from a COM Task object.

    Args:
        task: COM Task object from Project
        field_names: List of field/property names to read

    Returns:
        Tuple of (values_dict, errors_dict).
        values_dict: {field_name: current_value} (None if read failed)
        errors_dict: {field_name: error_message} (only for failed reads)
    """
    values = {}
    errors = {}
    for name in field_names:
        try:
            values[name] = getattr(task, name)
        except AttributeError:
            logger.warning("Field '%s' not found on task object", name)
            values[name] = None
            errors[name] = f"Field '{name}' not found on task object"
        except Exception as e:
            logger.warning(
                "Error reading field '%s': %s (type: %s)",
                name, e, type(e).__name__
            )
            values[name] = None
            errors[name] = f"{type(e).__name__}: {e}"
    return values, errors


def verify_task_write(
    task,
    requested: Dict[str, Any],
    max_retries: int = 3,
    retry_delays: tuple = (0.5, 1.0, 2.0),
) -> VerifyResult:
    """
    Verify a task mutation by re-reading fields from COM.

    This is the main integration point: after setting fields on a task,
    call this to get the {requested, actual, drifted} payload.

    Retries on mismatch to account for MS Project's asynchronous
    recalculation after writes.

    Args:
        task: COM Task object (after the write)
        requested: Dict of {field_name: value_we_set}
        max_retries: Number of retry attempts on mismatch (default 3)
        retry_delays: Seconds to wait between retries (default 0.5, 1.0, 2.0)

    Returns:
        VerifyResult with full drift analysis and per-field error info.
    """
    field_names = list(requested.keys())
    last_result = None

    for attempt in range(max_retries):
        actual, read_errors = read_task_fields(task, field_names)
        result = verify_fields(requested, actual)

        # Attach read errors to the corresponding FieldResults
        for fr in result.fields:
            if fr.field_name in read_errors:
                fr.error = read_errors[fr.field_name]

        if result.success:
            return result

        last_result = result

        # Don't sleep after the last attempt
        if attempt < max_retries - 1:
            delay = retry_delays[min(attempt, len(retry_delays) - 1)]
            logger.info(
                "Verify attempt %d/%d: %d fields drifted, retrying in %.1fs "
                "(async recalc may be in progress)",
                attempt + 1, max_retries, result.drifted_count, delay,
            )
            time.sleep(delay)

    # All retries exhausted — return last result with drift info
    logger.warning(
        "Verify-after-write: %d/%d fields drifted after %d attempts: %s",
        last_result.drifted_count,
        last_result.field_count,
        max_retries,
        [(f.field_name, f.drift_reason) for f in last_result.drifted_fields],
    )

    return last_result
