"""
Calculate Policy

Explicit calculate_project vs deferred calc. Suppresses automatic
calculation during batch operations so that 40 COM writes + 1 calc
is faster than 40 writes with auto-calc on a 10k-task file.

MS Project COM constants:
- pjAutomatic = -1  (Application.Calculation, PjCalculation enum)
- pjManual = 0
- Application.CalculateProject() recalculates the active project;
  Application.CalculateAll() recalculates every open project.
  (Project objects have no Calculate() method.)

NOTE: Testing against live MS Project remains required.

TODO: Add concurrency guard around original_mode capture in
    deferred_calc — overlapping calls can clobber each other's restore target.
TODO: Add timeout/cancellation around CalculateAll() for large files —
    synchronous recalc can block for minutes on 10k-task schedules.
"""

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

logger = logging.getLogger(__name__)


class CalcMode(IntEnum):
    """MS Project calculation modes (maps to pjCalculation enum)."""
    AUTOMATIC = -1  # pjAutomatic
    MANUAL = 0      # pjManual


@dataclass
class CalcState:
    """Snapshot of the calculation state."""
    mode: str                # "automatic" or "manual"
    mode_value: int          # Raw COM enum value
    was_deferred: bool       # True if we suppressed auto-calc
    original_mode: Optional[int] = None  # Mode before we changed it

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "mode_value": self.mode_value,
            "was_deferred": self.was_deferred,
            "original_mode": self.original_mode,
        }


def get_calc_mode(app) -> CalcMode:
    """Read the current calculation mode from COM."""
    try:
        raw = app.Calculation
        return CalcMode(raw)
    except Exception as e:
        # Catches ValueError (unknown enum), AttributeError (missing prop),
        # and pywintypes.com_error (dead/busy COM) without importing pywintypes.
        logger.warning("Could not read Calculation mode (%s): %s",
                       type(e).__name__, e)
        return CalcMode.AUTOMATIC  # Safe default


def set_calc_mode(app, mode: CalcMode) -> CalcMode:
    """
    Set the calculation mode on the COM Application.

    Args:
        app: COM Application object
        mode: CalcMode.AUTOMATIC or CalcMode.MANUAL

    Returns:
        The previous CalcMode.
    """
    previous = get_calc_mode(app)
    try:
        app.Calculation = int(mode)
        logger.info("Calculation mode: %s -> %s", previous.name, mode.name)
    except Exception as e:
        logger.error("Failed to set Calculation mode to %s: %s", mode.name, e)
        raise RuntimeError(
            f"Could not set calculation mode to {mode.name}: {e}"
        ) from e
    return previous


@contextmanager
def deferred_calc(app):
    """
    Context manager that suppresses auto-calculation for batch operations.

    Sets Application.Calculation to pjManual on entry, restores the
    original mode on exit. Does NOT trigger a recalc on exit — the
    caller decides when to recalculate (typically via calculate_project).

    Usage:
        with deferred_calc(app):
            # ... batch of COM writes ...
        calculate_project(app)  # explicit recalc after batch

    Yields:
        CalcState snapshot taken at entry.
    """
    original = get_calc_mode(app)
    state = CalcState(
        mode=original.name.lower(),
        mode_value=int(original),
        was_deferred=original == CalcMode.AUTOMATIC,
        original_mode=int(original),
    )

    if state.was_deferred:
        try:
            set_calc_mode(app, CalcMode.MANUAL)
        except RuntimeError:
            logger.error("Failed to defer calc; proceeding with auto-calc")
            state.was_deferred = False
            yield state
            return

    try:
        yield state
    finally:
        if state.was_deferred:
            try:
                set_calc_mode(app, original)
            except RuntimeError as restore_err:
                logger.error(
                    "Failed to restore calc mode to %s; "
                    "Application.Calculation may be stuck on MANUAL",
                    original.name,
                )
                raise RuntimeError(
                    f"deferred_calc could not restore calculation mode to "
                    f"{original.name}. Application may be stuck on MANUAL."
                ) from restore_err


def calculate_project(app, project=None) -> dict:
    """
    Trigger an explicit full recalculation.

    If project is given, activates it (if needed) and recalculates it via
    Application.CalculateProject(). Otherwise calls Application.CalculateAll().

    Args:
        app: COM Application object.
        project: Optional COM Project object. If None, recalcs all.

    Returns:
        dict with keys: recalculated (bool), scope (str), error (str|None)
    """
    scope = "project" if project else "all"
    try:
        if project:
            from .com_write import activate_project
            activate_project(app, project)
            app.CalculateProject()
        else:
            app.CalculateAll()
    except Exception as e:
        logger.error("Recalculation failed (scope=%s): %s", scope, e)
        return {"recalculated": False, "scope": scope, "error": str(e)}

    # Log success outside the try so a Name-access failure can't
    # mask a successful recalculation.
    try:
        name = project.Name if project else "all"
        logger.info("Recalculated: %s", name)
    except Exception:
        logger.info("Recalculated (scope=%s, name unavailable)", scope)
    return {"recalculated": True, "scope": scope, "error": None}


def get_calc_state(app) -> CalcState:
    """
    Read the current calculation state without changing anything.

    Returns:
        CalcState snapshot.
    """
    mode = get_calc_mode(app)
    return CalcState(
        mode=mode.name.lower(),
        mode_value=int(mode),
        was_deferred=False,
        original_mode=None,
    )
