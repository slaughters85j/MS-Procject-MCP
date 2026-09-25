"""
Session types, MS Project process detection, and the COM connect/launch step used by ProjectSession.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# Canonical MS Project process names for collision detection.
# Used by both psutil and tasklist paths to ensure consistency.
PROJECT_PROCESS_NAMES = ("WINPROJ.EXE",)


class SessionState(Enum):
    """Lifecycle states for the Project COM session."""
    DETACHED = "detached"
    ATTACHING = "attaching"
    ATTACHED = "attached"
    DETACHING = "detaching"
    ERROR = "error"


@dataclass
class SessionInfo:
    """Snapshot of current session state for the session_info tool."""
    state: str
    owner_pid: int
    project_path: Optional[str]
    project_count: int
    we_launched: bool
    com_class: str = "MSProject.Application"


def _find_existing_project_processes() -> list[int]:
    """
    Detect running WINPROJ.EXE processes.

    Uses psutil if available, falls back to tasklist on Windows.
    Returns a list of PIDs.
    """
    pids: list[int] = []

    # Try psutil first (cross-platform, reliable)
    try:
        import psutil
        for proc in psutil.process_iter(["name", "pid"]):
            if proc.info["name"] and proc.info["name"].upper() in PROJECT_PROCESS_NAMES:
                pids.append(proc.info["pid"])
        return pids
    except ImportError:
        pass

    # Fallback: tasklist on Windows
    try:
        import subprocess
        for proc_name in PROJECT_PROCESS_NAMES:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {proc_name}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.strip().splitlines():
                parts = line.strip('"').split('","')
                if len(parts) >= 2:
                    try:
                        pids.append(int(parts[1]))
                    except ValueError:
                        continue
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # Not on Windows or tasklist unavailable
        pass

    return pids


def wait_for_exit(pids, timeout: float = 20.0) -> bool:
    """Wait until none of pids is a running Project process. Returns True if they all exited."""
    import time
    deadline = time.monotonic() + timeout
    while set(pids) & set(_find_existing_project_processes()):
        if time.monotonic() >= deadline:
            logger.warning("Project process(es) %s still running %.0fs after Quit", pids, timeout)
            return False
        time.sleep(0.25)
    return True


def connect_app(win32com_client, existing_pids):
    """
    Attach to the running MS Project (when existing_pids is non-empty) or launch one.
    Returns (app, we_launched).
    """
    if existing_pids:
        # Attach to existing instance
        logger.info(
            "Found existing Project process(es): %s — attaching",
            existing_pids,
        )
        try:
            # Use com_retry if available for transient busy errors
            try:
                from src.com_retry import com_call
                app = com_call(
                    lambda: win32com_client.GetActiveObject(
                        "MSProject.Application"
                    ),
                    label="Session.GetActiveObject",
                )
            except ImportError:
                app = win32com_client.GetActiveObject(
                    "MSProject.Application"
                )
            we_launched = False
        except Exception as e:
            logger.warning(
                "GetActiveObject failed despite running process "
                "(PID %s): %s. This usually means the server is "
                "running elevated (admin) or in a different logon "
                "session than MS Project. Falling back to Dispatch.",
                existing_pids, e,
            )
            # Process exists but COM binding failed — try Dispatch
            app = win32com_client.Dispatch(
                "MSProject.Application"
            )
            we_launched = True
    else:
        # No existing instance — launch fresh
        logger.info("No existing Project instance — launching new one")
        app = win32com_client.Dispatch(
            "MSProject.Application"
        )
        we_launched = True
    return app, we_launched
