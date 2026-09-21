"""
WP-5: COM Proxy Refresh — TaskStore

Drop cached Task/Resource references after switch, save, or insert.
Re-resolve by UniqueID every time. Stale COM proxy detection with
one-retry re-resolve.

The TaskStore wraps COM Task/Resource collection access so that:
- No cached COM object references survive invalidation events
- All access resolves by UniqueID at point of use
- Stale proxy errors get one transparent retry
- Clear errors on true not-found vs COM failure

THREADING CONTRACT: This module assumes single-threaded, STA-compatible
    COM access. MS Project COM objects are STA (Single-Threaded Apartment);
    accessing them from a thread pool will cause crashes or undefined
    behavior, not just data races. If FastMCP ever dispatches tool calls
    off a thread pool, all COM access must be marshalled to the STA thread.
TODO(WP-6): Enforce STA thread affinity — either pin COM calls to a
    dedicated STA thread or assert caller is on the correct apartment.
TODO(WP-8): Performance — UniqueID iteration is O(n) per lookup.
    Consider building a UID→index mapping for large files, invalidated
    on the same events that clear the store.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# COM error codes that indicate a stale/disconnected proxy.
# We match on string fragments because importing pywintypes is
# Windows-only and we want the logic testable on Mac.
STALE_PROXY_INDICATORS = (
    "RPC_E_DISCONNECTED",
    "CO_E_OBJNOTCONNECTED",
    "RPC_E_SERVERFAULT",
    "0x800706BA",   # RPC server unavailable
    "0x80010108",   # Object invoked disconnected from clients
    "0x800706BE",   # Remote procedure call failed
    "Call was rejected",
)


class StoreEvent(Enum):
    """Events that invalidate cached COM references."""
    SAVE = "save"
    SWITCH = "switch"
    INSERT = "insert"
    MANUAL = "manual"


def _is_stale_proxy_error(exc: Exception) -> bool:
    """Check if an exception indicates a stale COM proxy."""
    exc_str = str(exc)
    exc_type = type(exc).__name__
    for indicator in STALE_PROXY_INDICATORS:
        if indicator in exc_str or indicator in exc_type:
            return True
    # pywintypes.com_error has an hresult attribute
    hresult = getattr(exc, "hresult", None)
    if hresult is not None:
        # Check known stale-proxy HRESULTs (as signed 32-bit)
        stale_hresults = {
            -2147023174,  # 0x800706BA - RPC server unavailable
            -2147417848,  # 0x80010108 - Object disconnected
            -2147023170,  # 0x800706BE - RPC call failed
        }
        if hresult in stale_hresults:
            return True
    return False


@dataclass
class ResolveResult:
    """Result of a UniqueID resolution attempt."""
    task: Any = None           # COM Task object, or None
    found: bool = False
    error: Optional[str] = None
    retried: bool = False      # True if we retried after stale proxy

    def to_dict(self) -> dict:
        return {
            "found": self.found,
            "error": self.error,
            "retried": self.retried,
        }


class TaskStore:
    """
    Stateless task/resource resolver for MS Project COM.

    Every lookup iterates the project's Tasks collection and matches
    by UniqueID. There is no persistent cache — this is deliberate.
    COM object references go stale after save, switch, or insert, and
    caching them causes silent corruption or crashes.

    If a COM call during resolution raises a stale-proxy error, the
    store retries once with a fresh collection reference.
    """

    def __init__(self, get_project_fn: Callable):
        """
        Args:
            get_project_fn: Zero-arg callable returning the active
                COM Project object (e.g., app.ActiveProject).
                Called on every resolve — never cached.
        """
        self._get_project = get_project_fn
        self._invalidation_count = 0
        self._resolve_count = 0
        self._retry_count = 0

    def invalidate(self, event: StoreEvent = StoreEvent.MANUAL) -> None:
        """
        Record that a COM-invalidating event occurred.

        In this stateless implementation there is no cache to clear —
        every resolve already fetches fresh from COM. This method
        exists as a diagnostic hook (tracks event counts) and as
        a stable API point: if a future version adds caching or
        index optimization, invalidation will actually purge state.

        Does NOT ensure fresh references on its own — that's
        inherent in the stateless resolve design.
        """
        self._invalidation_count += 1
        logger.info("TaskStore invalidated (event=%s, count=%d)",
                     event.value, self._invalidation_count)

    def _iterate_tasks(self, project) -> Tuple[List[Any], List[str]]:
        """
        Safely iterate the Tasks collection, skipping None entries.

        MS Project's Tasks collection can contain None slots
        (deleted tasks leave gaps).

        Returns:
            (tasks, errors) — list of COM Task objects and list of
            any non-fatal error messages encountered during iteration.
            Stale proxy errors are re-raised, not collected.
        """
        result = []
        errors = []
        try:
            for t in project.Tasks:
                if t is not None:
                    result.append(t)
        except Exception as e:
            if _is_stale_proxy_error(e):
                raise
            msg = f"Error iterating Tasks (collected {len(result)} " \
                  f"before failure): {e}"
            logger.warning(msg)
            errors.append(msg)
        return result, errors

    def resolve_task(self, unique_id: int) -> ResolveResult:
        """
        Find a task by UniqueID in the active project.

        Iterates the Tasks collection fresh each call. If a stale
        proxy error is caught, retries once with a fresh project
        reference.

        Args:
            unique_id: The task's UniqueID (int).

        Returns:
            ResolveResult with the COM Task or error info.
        """
        self._resolve_count += 1

        for attempt in range(2):  # At most one retry
            try:
                project = self._get_project()
                if project is None:
                    return ResolveResult(
                        error="No project is open."
                    )
                tasks, _iter_errors = self._iterate_tasks(project)
                for t in tasks:
                    try:
                        if t.UniqueID == unique_id:
                            return ResolveResult(
                                task=t,
                                found=True,
                                retried=attempt > 0,
                            )
                    except Exception as e:
                        if _is_stale_proxy_error(e):
                            raise  # Let outer handler retry
                        # Individual task COM error — skip it, log
                        logger.warning(
                            "COM error reading UniqueID on task: %s", e
                        )
                        continue

                # Exhausted collection without finding the UID
                return ResolveResult(
                    error=f"Task UniqueID {unique_id} not found.",
                    retried=attempt > 0,
                )

            except Exception as e:
                if attempt == 0 and _is_stale_proxy_error(e):
                    self._retry_count += 1
                    logger.warning(
                        "Stale proxy on resolve (uid=%d), retrying: %s",
                        unique_id, e,
                    )
                    continue  # Retry with fresh project reference
                # Second attempt or non-stale error
                return ResolveResult(
                    error=f"COM error resolving UniqueID {unique_id}: {e}",
                    retried=attempt > 0,
                )

        # Should not reach here, but defensive
        return ResolveResult(
            error=f"Unexpected: exhausted retries for UniqueID {unique_id}",
            retried=True,
        )

    def resolve_resource(self, unique_id: int) -> ResolveResult:
        """
        Find a resource by UniqueID in the active project.

        Same stale-proxy retry logic as resolve_task, but iterates
        the Resources collection instead.
        """
        self._resolve_count += 1

        for attempt in range(2):
            try:
                project = self._get_project()
                if project is None:
                    return ResolveResult(error="No project is open.")

                for r in project.Resources:
                    if r is None:
                        continue
                    try:
                        if r.UniqueID == unique_id:
                            return ResolveResult(
                                task=r,  # Reusing 'task' field for resource
                                found=True,
                                retried=attempt > 0,
                            )
                    except Exception as e:
                        if _is_stale_proxy_error(e):
                            raise
                        logger.warning(
                            "COM error reading UniqueID on resource: %s", e
                        )
                        continue

                return ResolveResult(
                    error=f"Resource UniqueID {unique_id} not found.",
                    retried=attempt > 0,
                )

            except Exception as e:
                if attempt == 0 and _is_stale_proxy_error(e):
                    self._retry_count += 1
                    logger.warning(
                        "Stale proxy on resource resolve (uid=%d), "
                        "retrying: %s", unique_id, e,
                    )
                    continue
                return ResolveResult(
                    error=f"COM error resolving resource "
                          f"UniqueID {unique_id}: {e}",
                    retried=attempt > 0,
                )

        return ResolveResult(
            error=f"Unexpected: exhausted retries for resource "
                  f"UniqueID {unique_id}",
            retried=True,
        )

    def get_all_tasks(self) -> Tuple[List[Any], Optional[str]]:
        """
        Get all non-None tasks from the active project.

        Returns:
            (tasks, error) — list of COM Task objects and optional
            error string. If iteration was partial (e.g., a non-stale
            COM error mid-collection), error describes the truncation.
            On stale proxy, retries once.
        """
        for attempt in range(2):
            try:
                project = self._get_project()
                if project is None:
                    return [], "No project is open."
                tasks, iter_errors = self._iterate_tasks(project)
                error_msg = "; ".join(iter_errors) if iter_errors else None
                return tasks, error_msg
            except Exception as e:
                if attempt == 0 and _is_stale_proxy_error(e):
                    self._retry_count += 1
                    logger.warning("Stale proxy on get_all_tasks, retrying")
                    continue
                return [], f"COM error listing tasks: {e}"
        return [], "Exhausted retries listing tasks."

    def get_stats(self) -> dict:
        """Diagnostic counters for the store."""
        return {
            "resolve_count": self._resolve_count,
            "invalidation_count": self._invalidation_count,
            "retry_count": self._retry_count,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_store: Optional[TaskStore] = None


def get_store() -> TaskStore:
    """
    Get the module-level TaskStore singleton.

    Must be initialized via init_store() before first use.
    """
    if _store is None:
        raise RuntimeError(
            "TaskStore not initialized. Call init_store() first."
        )
    return _store


def init_store(get_project_fn: Callable) -> TaskStore:
    """Initialize the module-level TaskStore singleton."""
    global _store
    _store = TaskStore(get_project_fn)
    return _store
