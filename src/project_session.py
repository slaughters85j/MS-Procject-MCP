"""
Session Ownership

Manages the lifecycle of a single MS Project COM connection.
One ProjectSession instance per server process. Explicit attach/detach.
Refuses to start if another COM client is already bound.

NOTE: Testing remains required — MS Project not available on build machine.
"""

import os
import logging
import atexit
from typing import Optional

logger = logging.getLogger(__name__)

# Types and process detection live in session_model; re-exported for existing imports.
# attach()/ensure_attached() call _find_existing_project_processes through this module's
# namespace so tests can patch src.project_session._find_existing_project_processes.
from .session_lifecycle import SessionLifecycleMixin  # noqa: E402
from .session_model import (  # noqa: F401,E402
    PROJECT_PROCESS_NAMES, SessionState, SessionInfo, _find_existing_project_processes, connect_app,
)

class ProjectSession(SessionLifecycleMixin):
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
            headless: Start Project with Visible=False.
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
    # Configuration
    # ------------------------------------------------------------------

    def configure(
        self,
        *,
        headless: Optional[bool] = None,
        allow_attach_existing: Optional[bool] = None,
        quit_on_detach: Optional[bool] = None,
    ) -> None:
        """
        Update session configuration before attach/detach.

        Only updates fields that are explicitly passed (not None).
        Raises if called while attached — reconfigure requires detach first.
        """
        if self._state == SessionState.ATTACHED:
            raise RuntimeError(
                "Cannot reconfigure while attached. Call detach() first."
            )
        if headless is not None:
            self._headless = headless
        if allow_attach_existing is not None:
            self._allow_attach_existing = allow_attach_existing
        if quit_on_detach is not None:
            self._quit_on_detach = quit_on_detach

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
        # TODO: Add threading.Lock around state transitions if
        # concurrent MCP dispatch is ever enabled. Currently single-threaded.
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

            self._app, self._we_launched = connect_app(win32com.client, existing_pids)

            # Configure visibility. Only an instance we launched may be hidden: hiding a
            # user's own Project window mid-session would take it away from them.
            if self._headless and self._we_launched:
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
    # Auto-attach
    # ------------------------------------------------------------------

    def ensure_attached(self) -> bool:
        """
        Attach to an already-running Project if not attached (never launches, never hides).

        Called before each tool so the hardening layer (identity, calc policy, UI, store, bulk)
        works without an explicit session_attach. Returns True when attached afterwards.
        """
        if self.is_attached:
            return True
        if not _find_existing_project_processes():
            return False
        try:
            self._headless = False
            self._allow_attach_existing = True
            self.attach()
        except Exception as e:
            logger.debug("Auto-attach failed: %s", e)
        return self.is_attached

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "ProjectSession":
        self.attach()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.detach()
        return False  # Don't suppress exceptions


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_session: Optional[ProjectSession] = None


def get_session() -> ProjectSession:
    """
    Get or create the module-level ProjectSession singleton.

    This replaces the old get_app() pattern. Instead of grabbing whatever
    COM object is active, we maintain a single managed session.

    TODO: Add reset_session() to handle ERROR state recovery.
    Currently a session stuck in ERROR requires process restart.
    """
    global _session
    if _session is None:
        _session = ProjectSession()
    return _session
