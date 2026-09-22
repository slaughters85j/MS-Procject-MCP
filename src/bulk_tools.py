"""
Bulk operation MCP tools.

Exposes bulk_update and bulk_status as MCP tools.
These are registered on the FastMCP instance in server.py.

NOTE: Testing against live MS Project remains required.
"""

import json
import logging
from typing import Optional

from .bulk_ops import (
    BulkAction, BulkItem, dry_run,
    apply,
)
from .task_store import get_store
from .project_session import get_session

logger = logging.getLogger(__name__)

# Module-level state for bulk_status
_last_result: Optional[dict] = None


def _parse_items(raw: str) -> list[BulkItem]:
    """
    Parse a JSON string into a list of BulkItem.

    Raises ValueError with a human-readable message on any parse error.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e

    if not isinstance(data, list):
        raise ValueError(
            f"Expected a JSON array of items, got {type(data).__name__}"
        )

    items = []
    for idx, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ValueError(
                f"item[{idx}]: expected object, got {type(entry).__name__}"
            )
        # Parse action
        if "action" not in entry:
            raise ValueError(
                f"item[{idx}]: missing required 'action' field"
            )
        action_str = entry["action"].lower()
        try:
            action = BulkAction(action_str)
        except ValueError:
            valid = ", ".join(a.value for a in BulkAction)
            raise ValueError(
                f"item[{idx}]: unknown action '{action_str}' "
                f"(valid: {valid})"
            )

        # Parse target_uid
        target_uid = entry.get("target_uid")
        if target_uid is not None:
            try:
                target_uid = int(target_uid)
            except (TypeError, ValueError):
                raise ValueError(
                    f"item[{idx}]: target_uid must be an integer, "
                    f"got {target_uid!r}"
                )

        # Parse fields
        fields = entry.get("fields", {})
        if not isinstance(fields, dict):
            raise ValueError(
                f"item[{idx}]: fields must be an object, "
                f"got {type(fields).__name__}"
            )

        items.append(BulkItem(
            action=action,
            target_uid=target_uid,
            fields=fields,
        ))

    return items


def register_bulk_tools(mcp):
    """Register bulk operation tools on the given FastMCP instance."""

    @mcp.tool()
    def bulk_update(items: str, mode: str = "dry_run") -> dict:
        """
        Execute a bulk update on tasks identified by UniqueID.

        Args:
            items: JSON array of objects, each with:
                   - action: "update" (required)
                   - target_uid: integer UniqueID of the task (required)
                   - fields: object of {field_name: value} to set
            mode: "dry_run" (default) to preview changes, or "apply"
                  to execute them.

        Returns:
            Dict with mode, total, succeeded, skipped, failed, drifted,
            and a per-item breakdown.  On error, returns {"error": "..."}.
        """
        global _last_result
        _last_result = None  # clear stale data before new run

        mode = mode.strip().lower()
        if mode not in ("dry_run", "apply"):
            return {"error": f"mode must be 'dry_run' or 'apply', got '{mode}'"}

        try:
            parsed = _parse_items(items)
        except ValueError as e:
            return {"error": str(e)}

        # Get session and store
        session = get_session()
        if not session.is_attached:
            return {"error": "Session not attached. Call session_attach first."}

        try:
            app = session.app
        except RuntimeError as e:
            return {"error": f"Cannot access COM Application: {e}"}

        try:
            project = app.ActiveProject
        except Exception as e:
            return {
                "error": f"Cannot access ActiveProject: "
                         f"{type(e).__name__}: {e}"
            }

        try:
            store = get_store()
        except RuntimeError as e:
            return {"error": f"TaskStore not initialized: {e}"}

        # Route to dry_run or apply
        try:
            if mode == "dry_run":
                bulk_result = dry_run(app, project, parsed, store)
            else:
                bulk_result = apply(app, project, parsed, store)
        except Exception as e:
            logger.error(
                "Bulk %s failed: %s: %s", mode, type(e).__name__, e,
            )
            return {"error": f"Bulk {mode} failed: {type(e).__name__}: {e}"}

        _last_result = bulk_result.to_dict()
        return _last_result

    @mcp.tool()
    def bulk_status() -> dict:
        """
        Return the result of the last bulk operation, or an empty status.

        Useful for checking results after a bulk_update call.
        """
        if _last_result is None:
            return {"status": "no bulk operations have been run"}
        return _last_result
