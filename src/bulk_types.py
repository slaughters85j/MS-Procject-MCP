"""
Bulk operation types (actions, items, per-item and aggregate results) and pre-flight validation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


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
