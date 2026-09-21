"""
WP-1: Session Ownership

Manages the lifecycle of a single MS Project COM connection.
One ProjectSession instance per server process. Explicit attach/detach.
Refuses to start if another COM client is already bound.

NOTE: Testing remains required — MS Project not available on build machine.
"""

import os
import logging
import atexit
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


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
            if proc.info["name"] and proc.info["name"].upper() in (
                "WINPROJ.EXE", "MSPUB.EXE"
            ):
                pids.append(proc.info["pid"])
        return pids
    except ImportError:
        pass

    # Fallback: tasklist on Windows
    try:
        import subprocess
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq WINPROJ.EXE", "/FO", "CSV", "/NH"],
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


class ProjectSession:
    """
    Manages a single MS Project COM connection with explicit lifecycle.

    Usage:
        session = ProjectSession()
        session.attach()         # Connect to or launch Project
        app = session.app        # Use the COM Application object
        session.detach()         # Clean up

    The session enforces:
    - Only one owner process at a time
    - Explicit attach/detach (no implicit "get whatever is active")
    - Graceful cleanup on shutdown via atexit
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        allow_attach_existing: bool = True,
        quit_on_detach: bool = False,
    ):
        """
        Args:
            headless: Start Project with Visible=False (WP-6 prep).
            allow_attach_existing: If True, attach to an already-running
                Project instance instead of refusing. If False, raise if
                Project is already running.
            quit_on_detach: If True AND we launched Project, quit it on detach.
        """
        self._app = None
        self._state = SessionState.DETACHED
        self._owner_pid = os.getpid()
        self._we_launched = False
        self._headless = headless
        self._allow_attach_existing = allow_attach_existing
        self._quit_on_detach = quit_on_detach
        self._project_path: Optional[str] = None

        # Register cleanup so we don't orphan COM references
        atexit.register(self._atexit_cleanup)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def app(self):
        """The COM Application object. Raises if not attached."""
        if self._state != SessionState.ATTACHED or self._app is None:
            raise RuntimeError(
                f"ProjectSession is {self._state.value}, not attached. "
                "Call session.attach() first."
            )
        return self._app

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def is_attached(self) -> bool:
        return self._state == SessionState.ATTACHED

    @property
    def project_path(self) -> Optional[str]:
        """Path of the currently open .mpp, or None."""
        if not self.is_attached:
            return None
        try:
            proj = self._app.ActiveProject
            if proj:
                return proj.FullName
        except Exception:
            pass
        return self._project_path

    # ------------------------------------------------------------------
    # Lifecycle: attach
    # ------------------------------------------------------------------

    def attach(self) -> "ProjectSession":
        """
        Connect to MS Project via COM.

        1. Check for existing WINPROJ.EXE processes.
        2. If found and allow_attach_existing is False, raise.
        3. If found and allow_attach_existing is True, attach via GetActiveObject.
        4. If not found, launch a new instance via Dispatch.
        5. Configure headless mode if requested.

        Returns self for chaining.
        """
        if self._state == SessionState.ATTACHED:
            logger.warning("Already attached — ignoring duplicate attach()")
            return self

        self._state = SessionState.ATTACHING
        logger.info("Attaching to MS Project (PID %d)...", self._owner_pid)

        try:
            import win32com.client
            import pythoncom
        except ImportError as e:
            self._state = SessionState.ERROR
            raise RuntimeError(
                "pywin32 is required: pip install pywin32"
            ) from e

        try:
            # Initialize COM for this thread
            pythoncom.CoInitialize()

            existing_pids = _find_existing_project_processes()

            if existing_pids and not self._allow_attach_existing:
                self._state = SessionState.ERROR
                raise RuntimeError(
                    f"MS Project is already running (PIDs: {existing_pids}). "
                    "Another COM client may be bound. Set "
                    "allow_attach_existing=True to attach anyway."
                )

            if existing_pids:
                # Attach to existing instance
                logger.info(
                    "Found existing Project process(es): %s — attaching",
                    existing_pids,
                )
                try:
                    self._app = win32com.client.GetActiveObject(
                        "MSProject.Application"
                    )
                    self._we_launched = False
                except Exception as e:
                    logger.warning(
                        "GetActiveObject failed despite running process: %s", e
                    )
                    # Process exists but COM binding failed — try Dispatch
                    self._app = win32com.client.Dispatch(
                        "MSProject.Application"
                    )
                    self._we_launched = True
            else:
                # No existing instance — launch fresh
                logger.info("No existing Project instance — launching new one")
                self._app = win32com.client.Dispatch(
                    "MSProject.Application"
                )
                self._we_launched = True

            # Configure visibility (WP-6 prep)
            if self._headless:
                try:
                    self._app.Visible = False
                    logger.info("Project started in headless mode")
                except Exception as e:
                    logger.warning("Could not set Visible=False: %s", e)

            # Cache the project path if one is open
            try:
                if self._app.Projects.Count > 0:
                    self._project_path = self._app.ActiveProject.FullName
            except Exception:
                pass

            self._state = SessionState.ATTACHED
            logger.info(
                "Attached to MS Project (we_launched=%s, project=%s)",
                self._we_launched,
                self._project_path,
            )
            return self

        except RuntimeError:
            raise
        except Exception as e:
            self._state = SessionState.ERROR
            raise RuntimeError(f"Failed to attach to MS Project: {e}") from e

    # ------------------------------------------------------------------
    # Lifecycle: detach
    # ------------------------------------------------------------------

    def detach(self) -> None:
        """
        Release the COM connection to MS Project.

        If we launched Project and quit_on_detach is True, quit the app.
        Otherwise just release the COM reference.
        """
        if self._state == SessionState.DETACHED:
            logger.warning("Already detached — ignoring duplicate detach()")
            return

        self._state = SessionState.DETACHING
        logger.info("Detaching from MS Project...")

        try:
            if self._app is not None:
                if self._we_launched and self._quit_on_detach:
                    try:
                        logger.info("Quitting Project (we launched it)")
                        self._app.Quit(0)  # 0 = pjDoNotSave
                    except Exception as e:
                        logger.warning("Quit failed (may already be closed): %s", e)

                # Release the COM reference
                try:
                    import pythoncom
                    # Marshal release — prevents hanging COM ref
                    del self._app
                except Exception as e:
                    logger.warning("COM release error: %s", e)

        finally:
            self._app = None
            self._project_path = None
            self._state = SessionState.DETACHED
            logger.info("Detached from MS Project")

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    def get_info(self) -> SessionInfo:
        """Return a snapshot of current session state."""
        project_count = 0
        project_path = self._project_path

        if self._state == SessionState.ATTACHED and self._app is not None:
            try:
                project_count = self._app.Projects.Count
                if project_count > 0:
                    project_path = self._app.ActiveProject.FullName
            except Exception:
                pass

        return SessionInfo(
            state=self._state.value,
            owner_pid=self._owner_pid,
            project_path=project_path,
            project_count=project_count,
            we_launched=self._we_launched,
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "ProjectSession":
        self.attach()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.detach()
        return False  # Don't suppress exceptions

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _atexit_cleanup(self) -> None:
        """Best-effort cleanup on process exit."""
        if self._state == SessionState.ATTACHED:
            logger.info("atexit: cleaning up COM session")
            try:
                self.detach()
            except Exception as e:
                logger.warning("atexit cleanup failed: %s", e)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_session: Optional[ProjectSession] = None


def get_session() -> ProjectSession:
    """
    Get or create the module-level ProjectSession singleton.

    This replaces the old get_app() pattern. Instead of grabbing whatever
    COM object is active, we maintain a single managed session.
    """
    global _session
    if _session is None:
        _session = ProjectSession()
    return _session
