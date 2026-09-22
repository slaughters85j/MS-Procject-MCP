"""
Live Integration Tests: Session Ownership

Tests ProjectSession attach/detach against a real MS Project instance.
Auto-skipped on non-Windows or when Project is not installed.
"""

import os
import sys

# Ensure project root on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.project_session import (
    ProjectSession,
    SessionState,
    _find_existing_project_processes,
)


class TestSessionAttachDetach:
    """Real COM attach/detach lifecycle."""

    def test_attach_creates_instance(self, com_init):
        session = ProjectSession(
            headless=True,
            quit_on_detach=True,
        )
        session.attach()
        try:
            assert session.state == SessionState.ATTACHED
            assert session.is_attached
            assert session._we_launched is True
            # COM app object should be live
            app = session.app
            assert app is not None
        finally:
            session.detach()

        assert session.state == SessionState.DETACHED

    def test_detach_quits_when_we_launched(self, com_init):
        import time
        session = ProjectSession(
            headless=True,
            quit_on_detach=True,
        )
        session.attach()
        assert session._we_launched is True
        session.detach()
        time.sleep(1.0)

        # Project process should be gone
        pids = _find_existing_project_processes()
        assert len(pids) == 0, (
            f"Project still running after quit_on_detach: PIDs {pids}"
        )

    def test_context_manager_lifecycle(self, com_init):
        with ProjectSession(
            headless=True, quit_on_detach=True
        ) as session:
            assert session.is_attached
            app = session.app
            app.FileNew()
            assert app.Projects.Count >= 1
        assert not session.is_attached

    def test_session_info_while_attached(self, com_init):
        session = ProjectSession(
            headless=True, quit_on_detach=True,
        )
        session.attach()
        try:
            info = session.get_info()
            assert info.state == "attached"
            assert info.owner_pid == os.getpid()
            assert info.we_launched is True
        finally:
            session.detach()

    def test_headless_mode_invisible(self, com_init):
        session = ProjectSession(
            headless=True, quit_on_detach=True,
        )
        session.attach()
        try:
            assert session.app.Visible is False or not session.app.Visible
        finally:
            session.detach()

    def test_double_attach_is_noop(self, com_init):
        session = ProjectSession(
            headless=True, quit_on_detach=True,
        )
        session.attach()
        try:
            session.attach()  # Should warn, not crash
            assert session.state == SessionState.ATTACHED
        finally:
            session.detach()
