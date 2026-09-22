"""
MCP tools for task/resource resolution.

Registers tools that let the LLM orchestrator:
- Resolve a task by UniqueID (with stale proxy retry)
- Resolve a resource by UniqueID
- Invalidate the store (signal save/switch/insert)
- Get store diagnostics
"""

import logging
from .task_store import (
    StoreEvent,
    get_store,
)

logger = logging.getLogger(__name__)


def register_store_tools(mcp):
    """Register task store MCP tools."""

    @mcp.tool()
    def resolve_task(unique_id: int) -> dict:
        """
        Find a task by UniqueID in the active project.

        Resolves fresh from COM each call — no cached references.
        Automatically retries once on stale COM proxy errors.

        Args:
            unique_id: The task's UniqueID (integer).

        Returns:
            Dict with found (bool), error (str|None), retried (bool),
            and basic task info if found.
        """
        store = get_store()
        result = store.resolve_task(unique_id)
        response = result.to_dict()

        if result.found and result.task:
            try:
                response["task"] = {
                    "unique_id": result.task.UniqueID,
                    "name": result.task.Name,
                    "id": result.task.ID,
                }
            except Exception as e:
                response["task"] = {"read_error": str(e)}

        return response

    @mcp.tool()
    def resolve_resource(unique_id: int) -> dict:
        """
        Find a resource by UniqueID in the active project.

        Args:
            unique_id: The resource's UniqueID (integer).

        Returns:
            Dict with found (bool), error (str|None), retried (bool),
            and basic resource info if found.
        """
        store = get_store()
        result = store.resolve_resource(unique_id)
        response = result.to_dict()

        if result.found and result.task:
            try:
                response["resource"] = {
                    "unique_id": result.task.UniqueID,
                    "name": result.task.Name,
                    "id": result.task.ID,
                }
            except Exception as e:
                response["resource"] = {"read_error": str(e)}

        return response

    @mcp.tool()
    def invalidate_store(event: str = "manual") -> dict:
        """
        Signal that COM references may be stale.

        Record that a save, switch, or insert occurred. In the
        current stateless design, resolves are always fresh; this
        logs the event for diagnostics and will purge caches if
        a future version adds indexing.

        Args:
            event: One of "save", "switch", "insert", "manual".

        Returns:
            Dict with invalidation count.
        """
        event_map = {
            "save": StoreEvent.SAVE,
            "switch": StoreEvent.SWITCH,
            "insert": StoreEvent.INSERT,
            "manual": StoreEvent.MANUAL,
        }
        ev = event_map.get(event.strip().lower())
        if ev is None:
            return {
                "error": f"Invalid event '{event}'. "
                         f"Use: {', '.join(event_map.keys())}"
            }

        store = get_store()
        store.invalidate(ev)
        return store.get_stats()

    @mcp.tool()
    def store_stats() -> dict:
        """
        Get diagnostic counters for the task store.

        Returns:
            Dict with resolve_count, invalidation_count, retry_count.
        """
        store = get_store()
        return store.get_stats()
