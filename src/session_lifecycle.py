"""
Detach, session info, and process-exit cleanup for ProjectSession (mixed into the class).
"""

import logging

from .session_model import SessionInfo, SessionState

logger = logging.getLogger(__name__)


class SessionLifecycleMixin:
    """Lifecycle methods of ProjectSession that do not depend on process detection."""

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
                    del self._app
                except Exception as e:
                    logger.warning("COM release error: %s", e)

            # Balance the CoInitialize() from attach()
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception as e:
                logger.warning("CoUninitialize error: %s", e)

        finally:
            self._app = None
            self._project_path = None
            self._state = SessionState.DETACHED
            logger.info("Detached from MS Project")

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
    # Process-exit cleanup
    # ------------------------------------------------------------------

    def _atexit_cleanup(self) -> None:
        """
        Best-effort cleanup on process exit.

        An instance this server launched is usually hidden; left running it would be an
        invisible orphan the user cannot close. Quit it when everything in it is saved;
        if anything is unsaved, show it instead so no work is discarded.
        """
        if self._state != SessionState.ATTACHED:
            return
        logger.info("atexit: cleaning up COM session")
        try:
            if self._we_launched and self._app is not None:
                app = self._app
                unsaved = [app.Projects(i).Name for i in range(1, app.Projects.Count + 1)
                           if not app.Projects(i).Saved]
                if unsaved:
                    logger.warning("atexit: leaving launched Project open and visible (unsaved: %s)", unsaved)
                    app.Visible = True
                else:
                    self._quit_on_detach = True
            self.detach()
        except Exception as e:
            logger.warning("atexit cleanup failed: %s", e)
