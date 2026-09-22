"""
Active-Project Identity

Ensures every mutating operation targets the correct project.
Never trust "whatever is active" — require explicit project identity.

Identity scheme: canonical file path (os.path.normcase + normpath).
Validation: compare requested identity against the active project before mutation.

NOTE: Testing against live MS Project remains required.
"""

import hashlib
import logging
import ntpath
import os
from dataclasses import dataclass
from functools import wraps
from typing import Optional, Callable

logger = logging.getLogger(__name__)


def canonical_path(path: str) -> str:
    """
    Normalize a project file path to a canonical form for comparison.

    Uses ntpath unconditionally so that Windows-style paths are
    lowercased and separator-normalized even on macOS/Linux hosts.
    This is critical because MS Project always returns Windows paths.
    """
    return ntpath.normcase(ntpath.normpath(path))


def path_hash(path: str) -> str:
    """
    Short SHA-256 hash of the canonical path.

    Useful as a compact project_id in tool calls.
    First 12 hex chars — collision-safe for any realistic project count.
    """
    return hashlib.sha256(canonical_path(path).encode()).hexdigest()[:12]


@dataclass
class ProjectIdentity:
    """Resolved identity of a project."""
    canonical: str       # Normalized file path
    hash_id: str         # Short hash for compact references
    display_name: str    # Filename for human-readable messages

    @classmethod
    def from_path(cls, path: str) -> "ProjectIdentity":
        canon = canonical_path(path)
        # Use ntpath.basename to correctly extract filename from Windows
        # paths even when running on macOS/Linux (where \ is not a separator).
        display = ntpath.basename(path) or os.path.basename(path)
        return cls(
            canonical=canon,
            hash_id=path_hash(canon),
            display_name=display,
        )

    def matches(self, other_path: str) -> bool:
        """Check if another path refers to the same project."""
        return canonical_path(other_path) == self.canonical


class ProjectMismatchError(Exception):
    """Raised when a tool targets a project that isn't currently active."""

    def __init__(self, requested: str, active: str):
        self.requested = requested
        self.active = active
        super().__init__(
            f"Project mismatch: requested '{requested}' but active project "
            f"is '{active}'. Use switch_project to change the active project."
        )


def get_active_identity(app) -> Optional[ProjectIdentity]:
    """
    Get the identity of the currently active project from COM.

    Args:
        app: The COM Application object (MSProject.Application)

    Returns:
        ProjectIdentity if a project is open, None otherwise.
    """
    try:
        if app.Projects.Count == 0:
            return None
        proj = app.ActiveProject
        if proj and proj.FullName:
            return ProjectIdentity.from_path(proj.FullName)
    except Exception as e:
        logger.warning("Could not determine active project identity: %s", e)
    return None


def validate_project_target(app, project_id: str) -> ProjectIdentity:
    """
    Validate that project_id matches the active project.

    Args:
        app: COM Application object
        project_id: File path or hash identifying the target project

    Returns:
        The active ProjectIdentity if validation passes.

    Raises:
        ProjectMismatchError: If project_id doesn't match the active project.
        RuntimeError: If no project is open.
    """
    active = get_active_identity(app)
    if active is None:
        raise RuntimeError("No project is currently open.")

    # Match by hash (with canonical path cross-check for defense in depth)
    if project_id == active.hash_id:
        # Hash matched — verify canonical path hasn't changed underneath us
        fresh = get_active_identity(app)
        if fresh and fresh.hash_id == active.hash_id:
            return active
        logger.warning("Hash matched but active project shifted during validation")

    # Match by canonical path
    if canonical_path(project_id) == active.canonical:
        return active

    # No match: the mismatch this identity check exists to catch
    raise ProjectMismatchError(
        requested=project_id,
        active=f"{active.display_name} ({active.hash_id})"
    )


def require_project_id(get_app_fn: Callable):
    """
    Decorator factory for mutating MCP tools.

    TODO: TOCTOU risk — validation and execution are not atomic.
    In the current single-threaded MCP model this is safe, but if
    concurrent dispatch is ever enabled, pin the project COM reference
    during validation and pass it through to the wrapped function.

    Wraps a tool function so it:
    1. Requires a project_id parameter
    2. Validates project_id against the active project before execution
    3. Passes the validated app to the wrapped function

    The decorated function must accept project_id as its first parameter.
    The get_app_fn callable returns the COM Application object.

    Usage:
        @mcp.tool()
        @require_project_id(get_app)
        def update_task(project_id: str, unique_id: int, ...) -> str:
            app = get_app()
            ...
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            project_id = kwargs.get("project_id") or (args[0] if args else None)
            if not project_id:
                raise ValueError(
                    f"project_id is required for {fn.__name__}. "
                    "Use get_project_identity to find the current project's ID."
                )
            app = get_app_fn()
            validate_project_target(app, project_id)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
