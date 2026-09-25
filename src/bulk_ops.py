"""
Idempotent Bulk Operations

Bulk add/update with dry-run/apply, per-item results, no silent partial
success.  Every item gets an explicit status: ok, skipped (idempotent),
drifted (verify-after-write detected recalc), or error.

The apply path wraps the entire batch in:
  - deferred_calc — one recalc after all writes, not N
  - ui_lock       — ScreenUpdating frozen while mutating

THREADING CONTRACT
  All public functions assume they run on the COM STA thread that owns
  the Application object.  Do NOT call from a thread-pool worker.
  ui_lock and deferred_calc share this assumption.

NOTE: Testing against live MS Project remains required.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .bulk_fields import normalized_or_error

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums and dataclasses
# ---------------------------------------------------------------------------

class BulkAction(Enum):
    """Supported bulk operations."""
    UPDATE = "update"
    INSERT = "insert"   # TODO: implement
    DELETE = "delete"   # TODO: implement


@dataclass
class BulkItem:
    """One item in a bulk request."""
    action: BulkAction
    target_uid: Optional[int]  # required for UPDATE/DELETE, None for INSERT
    fields: Dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "target_uid": self.target_uid,
            "fields": dict(self.fields),
        }


@dataclass
class ItemResult:
    """Per-item outcome from a bulk operation."""
    unique_id: Optional[int]
    action: str
    status: str          # "ok", "skipped", "error", "drifted"
    fields_written: Dict[str, Any] = field(default_factory=dict)
    verification: Optional[dict] = None
    error: Optional[str] = None
    current_values: Dict[str, Any] = field(default_factory=dict)  # dry run: values before the change

    def to_dict(self) -> dict:
        d = {
            "unique_id": self.unique_id,
            "action": self.action,
            "status": self.status,
        }
        if self.fields_written:
            d["fields_written"] = self.fields_written
        if self.current_values:
            d["current_values"] = self.current_values
        if self.verification is not None:
            d["verification"] = self.verification
        if self.error is not None:
            d["error"] = self.error
        return d


@dataclass
class BulkResult:
    """Aggregate outcome of a bulk operation."""
    mode: str           # "dry_run" or "apply"
    total: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    drifted: int = 0
    items: List[ItemResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "total": self.total,
            "succeeded": self.succeeded,
            "skipped": self.skipped,
            "failed": self.failed,
            "drifted": self.drifted,
            "items": [it.to_dict() for it in self.items],
        }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_IMPLEMENTED_ACTIONS = {BulkAction.UPDATE}


def validate_bulk_items(items: List[BulkItem]) -> List[str]:
    """
    Pre-flight validation for a list of BulkItems.

    Returns a list of human-readable error strings.  An empty list means
    all items passed validation.
    """
    errors: List[str] = []
    if not items:
        errors.append("items list is empty")
        return errors

    for idx, item in enumerate(items):
        prefix = f"item[{idx}]"
        if item.action not in _IMPLEMENTED_ACTIONS:
            errors.append(
                f"{prefix}: action '{item.action.value}' is not yet "
                f"implemented (supported: "
                f"{', '.join(a.value for a in _IMPLEMENTED_ACTIONS)})"
            )
        if item.action in (BulkAction.UPDATE, BulkAction.DELETE):
            if item.target_uid is None:
                errors.append(
                    f"{prefix}: target_uid is required for "
                    f"'{item.action.value}'"
                )
        if not item.fields:
            errors.append(f"{prefix}: fields dict is empty")

    return errors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fields_already_match(task, fields: Dict[str, Any]) -> bool:
    """Return True if every field on the COM task already equals the request."""
    for name, desired in fields.items():
        try:
            current = getattr(task, name)
        except Exception:
            return False   # can't read -> can't confirm match
        if current != desired:
            return False
    return True


def _read_current_fields(task, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Read current values for the requested field names, best-effort."""
    current: Dict[str, Any] = {}
    for name in fields:
        try:
            current[name] = getattr(task, name)
        except Exception as e:
            current[name] = f"<read error: {type(e).__name__}: {e}>"
    return current


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

def dry_run(app, project, items: List[BulkItem], store) -> BulkResult:
    """
    Validate each item, resolve targets, report what WOULD change.

    No mutations.  Items whose current values already match the request
    are marked "skipped" (idempotent no-op).

    Args:
        app:     COM Application object (for store resolution)
        project: COM Project object (unused, kept for symmetry with apply)
        items:   List of BulkItem to evaluate
        store:   TaskStore instance for UniqueID resolution

    Returns:
        BulkResult with mode="dry_run" and per-item details.
    """
    result = BulkResult(mode="dry_run", total=len(items))

    validation_errors = validate_bulk_items(items)
    if validation_errors:
        result.failed = max(len(items), 1)
        result.items = [
            ItemResult(
                unique_id=None,
                action="validate",
                status="error",
                error="; ".join(validation_errors),
            )
        ]
        return result

    for item in items:
        uid = item.target_uid
        resolve = store.resolve_task(uid)
        if not resolve.found:
            result.failed += 1
            result.items.append(ItemResult(
                unique_id=uid,
                action=item.action.value,
                status="error",
                error=resolve.error or f"Task UniqueID {uid} not found",
            ))
            continue

        task = resolve.task
        fields, error = normalized_or_error(project, task, item.fields)
        if error:
            result.failed += 1
            result.items.append(ItemResult(unique_id=uid, action=item.action.value, status="error", error=error))
        elif _fields_already_match(task, fields):
            result.skipped += 1
            result.items.append(ItemResult(
                unique_id=uid,
                action=item.action.value,
                status="skipped",
            ))
        else:
            result.succeeded += 1
            result.items.append(ItemResult(
                unique_id=uid,
                action=item.action.value,
                status="ok",
                fields_written=fields,                              # what apply would write
                current_values=_read_current_fields(task, fields),  # what is there now
            ))

    return result


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply(app, project, items: List[BulkItem], store) -> BulkResult:
    """
    Execute a bulk mutation: resolve, write, verify per item.

    The entire batch is wrapped in deferred_calc and ui_lock.
    After all items, calculate_project triggers a single recalc.

    Per-item COM errors are captured and reported; they do NOT abort the
    batch.  The caller gets an explicit status for every item.

    Args:
        app:     COM Application object
        project: COM Project object (for calculate_project scoping)
        items:   List of BulkItem to execute
        store:   TaskStore instance for UniqueID resolution

    Returns:
        BulkResult with mode="apply" and per-item details including
        verify-after-write payloads.
    """
    from .calc_policy import deferred_calc, calculate_project
    from .ui_lock import ui_lock
    from .verify_write import verify_task_write

    result = BulkResult(mode="apply", total=len(items))

    validation_errors = validate_bulk_items(items)
    if validation_errors:
        result.failed = max(len(items), 1)
        result.items = [
            ItemResult(
                unique_id=None,
                action="validate",
                status="error",
                error="; ".join(validation_errors),
            )
        ]
        return result

    with deferred_calc(app):
        with ui_lock(app):
            for item in items:
                ir = _apply_one(item, store, verify_task_write, project)
                result.items.append(ir)
                if ir.status == "ok":
                    result.succeeded += 1
                elif ir.status == "skipped":
                    result.skipped += 1
                elif ir.status == "drifted":
                    result.drifted += 1
                else:
                    result.failed += 1

    # Single recalc after all writes
    try:
        calc_result = calculate_project(app, project)
        logger.info("Post-batch recalc: %s", calc_result)
    except Exception as e:
        logger.error(
            "Post-batch calculate_project failed: %s: %s",
            type(e).__name__, e,
        )

    return result


def _apply_one(item: BulkItem, store, verify_fn, project=None) -> ItemResult:
    """
    Resolve, write, verify a single BulkItem.

    Returns an ItemResult.  Never raises; COM errors are captured.
    """
    uid = item.target_uid

    # Resolve
    resolve = store.resolve_task(uid)
    if not resolve.found:
        return ItemResult(
            unique_id=uid,
            action=item.action.value,
            status="error",
            error=resolve.error or f"Task UniqueID {uid} not found",
        )

    task = resolve.task
    fields, error = normalized_or_error(project, task, item.fields)
    if error:
        return ItemResult(unique_id=uid, action=item.action.value, status="error", error=error)

    # Idempotency check: skip if already matches
    if _fields_already_match(task, fields):
        return ItemResult(
            unique_id=uid,
            action=item.action.value,
            status="skipped",
        )

    # Write fields
    written = {}
    for name, value in fields.items():
        try:
            setattr(task, name, value)
            written[name] = value
        except Exception as e:
            logger.error(
                "Failed to write field '%s' on task %d: %s: %s",
                name, uid, type(e).__name__, e,
            )
            return ItemResult(
                unique_id=uid,
                action=item.action.value,
                status="error",
                fields_written=written,
                error=f"Write failed on field '{name}': "
                      f"{type(e).__name__}: {e}",
            )

    # Verify-after-write
    try:
        vresult = verify_fn(task, fields)
        verification = vresult.to_dict()
    except Exception as e:
        logger.error(
            "Verify-after-write failed for task %d: %s: %s",
            uid, type(e).__name__, e,
        )
        verification = {"error": f"{type(e).__name__}: {e}"}

    if verification.get("success", False):
        return ItemResult(
            unique_id=uid,
            action=item.action.value,
            status="ok",
            fields_written=written,
            verification=verification,
        )
    else:
        return ItemResult(
            unique_id=uid,
            action=item.action.value,
            status="drifted",
            fields_written=written,
            verification=verification,
        )
