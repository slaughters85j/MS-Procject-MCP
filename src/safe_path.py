"""
MSPROJECT_SAFE_ROOT path confinement (adapted from the 4nswer fork).

When the environment variable MSPROJECT_SAFE_ROOT is set, all file-path-taking
tools must route through validate_safe_path() before touching the filesystem.
Fail-closed: if set, paths outside the safe root are rejected.  If unset,
behaviour is unchanged (no confinement).

Resolves symlinks and rejects directory-traversal attempts (../).
"""

import os
import sys

_SAFE_ROOT: str | None = None
_SAFE_ROOT_RESOLVED: str | None = None


def _init_safe_root() -> None:
    """Read MSPROJECT_SAFE_ROOT once at import time."""
    global _SAFE_ROOT, _SAFE_ROOT_RESOLVED
    raw = os.environ.get("MSPROJECT_SAFE_ROOT", "").strip()
    if not raw:
        _SAFE_ROOT = None
        _SAFE_ROOT_RESOLVED = None
        return
    resolved = os.path.realpath(raw)
    if not os.path.isdir(resolved):
        print(
            f"[safe_path] WARNING: MSPROJECT_SAFE_ROOT={raw!r} "
            f"does not exist or is not a directory. "
            f"All file operations will be refused.",
            file=sys.stderr,
        )
    # Ensure trailing separator for prefix matching
    _SAFE_ROOT = raw
    _SAFE_ROOT_RESOLVED = resolved.rstrip(os.sep) + os.sep


_init_safe_root()


def is_confined() -> bool:
    """Return True if path confinement is active."""
    return _SAFE_ROOT_RESOLVED is not None


def get_safe_root() -> str | None:
    """Return the configured safe root (raw value), or None."""
    return _SAFE_ROOT


def validate_safe_path(file_path: str) -> str:
    """
    Validate and resolve *file_path* against MSPROJECT_SAFE_ROOT.

    Returns the resolved absolute path if it falls under the safe root.
    Raises ValueError with a human-readable message if it does not.
    If MSPROJECT_SAFE_ROOT is not set, returns the path unchanged.
    """
    if _SAFE_ROOT_RESOLVED is None:
        return file_path

    # Resolve the candidate path (follows symlinks, normalises ..)
    resolved = os.path.realpath(os.path.abspath(file_path))

    # The resolved path must start with the safe root prefix.
    # We also accept an exact match (the root directory itself).
    if not (resolved + os.sep).startswith(_SAFE_ROOT_RESOLVED):
        raise ValueError(
            f"Path confinement violation: {file_path!r} resolves to "
            f"{resolved!r} which is outside MSPROJECT_SAFE_ROOT={_SAFE_ROOT!r}"
        )

    return resolved


def reload_safe_root() -> None:
    """Re-read MSPROJECT_SAFE_ROOT.  Intended for tests only."""
    _init_safe_root()
