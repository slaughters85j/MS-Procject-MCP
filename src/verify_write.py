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
from datetime import datetime
from typing import Any, Dict, List, Optional

# Comparison rules live in drift_rules; re-exported here for existing imports.
from .drift_rules import (  # noqa: F401
    DriftReason, DATE_TOLERANCE, DURATION_TOLERANCE_MINUTES, COST_TOLERANCE,
    _classify_drift, _values_match,
)

logger = logging.getLogger(__name__)


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
