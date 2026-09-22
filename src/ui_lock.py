"""
Concurrency and UI — UI lock

Protects tool calls from the MS Project window. Three modes:
- INVISIBLE: Application.Visible = False. No window, nothing to click.
  ui_lock() is a no-op. This is the only mode that keeps a user out of
  Project during a tool call.
- LOCKED: Window visible. ui_lock() sets ScreenUpdating = False and a
  status bar message for the duration of each tool call, then restores.
- OPEN: Window visible, no protection. ui_lock() is a no-op.

LIMITATION: Project has no Application.Interactive property (Excel does).
    ScreenUpdating = False stops repaints but does NOT block mouse or
    keyboard input. LOCKED mode reduces flicker and signals "busy"; it
    does not stop a user from clicking. Use INVISIBLE for unattended work.

MS Project COM facts used here (Microsoft Learn, Project VBA reference):
- Application.Visible: read/write Boolean
- Application.ScreenUpdating: read/write Boolean
- Application.StatusBar: read/write Variant. Reads False while the default
  text shows; setting it to False restores the default text.

THREADING CONTRACT: This module assumes single-threaded, STA-compatible
    COM access, same as task_store.py. MS Project COM objects are
    STA (Single-Threaded Apartment); calling them from a thread pool
    crashes or corrupts state. The module-level mode and lock state below
    are not thread-safe for the same reason, and they persist for the
    life of the server process.

NOTE: Testing against live MS Project remains required.
"""

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)

STATUS_MESSAGE = "MCP tool executing..."


class UIMode(Enum):
    """How the server protects tool calls from the Project window."""
    INVISIBLE = "invisible"
    LOCKED = "locked"
    OPEN = "open"


@dataclass
class UILockState:
    """Snapshot of the UI mode, any active per-call lock, and problems."""
    mode: str  # A UIMode value, or "unknown" if Visible could not be read
    screen_updating_was: Optional[bool] = None  # Saved value while locked
    locked_at: Optional[float] = None           # time.time() at lock start
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "screen_updating_was": self.screen_updating_was,
            "locked_at": self.locked_at,
            "errors": list(self.errors),
        }


# Module-level state (single STA thread — see THREADING CONTRACT).
_configured_mode: Optional[UIMode] = None   # Last mode set via set_ui_mode
_active_lock: Optional[UILockState] = None  # Non-None while ui_lock holds
_last_restore_error: Optional[str] = None   # Kept until set_ui_mode succeeds


def _com_error(action: str, exc: Exception) -> str:
    """Log a COM failure and return a message fit for a tool response."""
    msg = f"{action} failed ({type(exc).__name__}): {exc}"
    logger.error(msg)
    return msg


def get_ui_mode(app) -> UIMode:
    """
    Read the effective UI mode.

    Visible = False reads as INVISIBLE. A visible window reads as OPEN
    only if OPEN was chosen via set_ui_mode; otherwise it reads as LOCKED,
    so a visible window is protected by default.

    Raises:
        RuntimeError: Application.Visible could not be read.
    """
    try:
        visible = bool(app.Visible)
    except Exception as e:
        raise RuntimeError(_com_error("Reading Application.Visible", e)) from e
    if not visible:
        return UIMode.INVISIBLE
    return UIMode.OPEN if _configured_mode == UIMode.OPEN else UIMode.LOCKED


def set_ui_mode(app, mode: UIMode) -> UIMode:
    """
    Apply a UI mode and remember it for ui_lock().

    Every mode sets ScreenUpdating = True, because LOCKED only turns it
    off inside ui_lock(). This also recovers a screen left frozen by a
    failed restore.

    Returns:
        The previous effective UIMode.

    Raises:
        RuntimeError: Called inside ui_lock(), or a COM read/write failed.
    """
    global _configured_mode, _last_restore_error
    if _active_lock is not None:
        raise RuntimeError(
            "Cannot change UI mode while a UI lock is active. "
            "Call set_ui_mode outside a locked tool call."
        )
    previous = get_ui_mode(app)
    try:
        app.ScreenUpdating = True
        app.Visible = mode != UIMode.INVISIBLE
    except Exception as e:
        raise RuntimeError(
            _com_error(f"Setting UI mode to '{mode.value}'", e)
        ) from e
    _configured_mode = mode
    _last_restore_error = None
    logger.info("UI mode: %s -> %s", previous.value, mode.value)
    return previous


def _restore(app, state: UILockState, status_set: bool) -> None:
    """
    Undo ui_lock's changes. Log and record failures; never raise.

    A failure stays in _last_restore_error until set_ui_mode succeeds, so a
    later clean restore cannot hide it before an agent reads get_ui_state.
    """
    global _last_restore_error
    failures = []
    try:
        app.ScreenUpdating = state.screen_updating_was
    except Exception as e:
        failures.append(_com_error(
            "Restoring ScreenUpdating (screen may stay frozen; "
            "call set_ui_mode to recover)", e,
        ))
    if status_set:
        try:
            app.StatusBar = False  # False restores Project's default text
        except Exception as e:
            failures.append(_com_error("Clearing StatusBar", e))
    state.errors.extend(failures)
    if failures:
        _last_restore_error = "; ".join(failures)


@contextmanager
def ui_lock(app):
    """
    Freeze screen updates for one tool call in LOCKED mode.

    On entry: save ScreenUpdating, set it False, show STATUS_MESSAGE.
    On exit (always, even on exception): restore ScreenUpdating and clear
    the status bar. No-op in INVISIBLE or OPEN mode, and when nested
    inside another ui_lock (the outer lock restores).

    Never raises its own errors. COM failures are logged and added to the
    yielded state's errors list so the caller can put them in the tool
    response; the tool call still runs. Exceptions from the with-body
    propagate unchanged.

    Yields:
        UILockState. Check .errors after the with-block.
    """
    global _active_lock
    if _active_lock is not None:
        yield _active_lock
        return

    state = UILockState(mode="unknown")
    try:
        state.mode = get_ui_mode(app).value
    except RuntimeError as e:
        state.errors.append(f"UI lock skipped: {e}")
    if state.mode != UIMode.LOCKED.value:
        yield state
        return

    lock_error = None
    try:
        saved = bool(app.ScreenUpdating)
        app.ScreenUpdating = False
    except Exception as e:
        lock_error = _com_error("UI lock skipped: freezing ScreenUpdating", e)
    if lock_error:
        state.errors.append(lock_error)
        yield state
        return

    state.screen_updating_was = saved
    state.locked_at = time.time()
    status_set = False
    try:
        app.StatusBar = STATUS_MESSAGE
        status_set = True
    except Exception as e:
        state.errors.append(_com_error("Setting StatusBar", e))

    _active_lock = state
    try:
        yield state
    finally:
        _active_lock = None
        _restore(app, state, status_set)


def get_ui_state(app) -> UILockState:
    """
    Read-only snapshot: effective mode, active lock (if any), and problems.

    Reports the last restore failure and a frozen screen (visible window,
    ScreenUpdating False, no active lock) so an agent can diagnose and
    recover with set_ui_mode.

    Raises:
        RuntimeError: Application.Visible could not be read.
    """
    mode = get_ui_mode(app)
    state = UILockState(mode=mode.value)
    if _active_lock is not None:
        state.screen_updating_was = _active_lock.screen_updating_was
        state.locked_at = _active_lock.locked_at
        state.errors.extend(_active_lock.errors)
    if _last_restore_error:
        state.errors.append(f"Last UI lock restore failed: {_last_restore_error}")
    if mode != UIMode.INVISIBLE and _active_lock is None:
        try:
            if not app.ScreenUpdating:
                state.errors.append(
                    "ScreenUpdating is False outside a tool call, so the "
                    "Project window is frozen. Call set_ui_mode to recover."
                )
        except Exception as e:
            state.errors.append(
                _com_error("Reading Application.ScreenUpdating", e)
            )
    return state
