"""
Session Ownership Tests

Tests for ProjectSession lifecycle management.
These tests mock the COM layer so they run on any platform.
Live COM tests require MS Project on Windows — see integration/test_project_session_live.py.

NOTE: Testing against live MS Project remains required.
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.project_session import (
    ProjectSession,
    SessionState,
    PROJECT_PROCESS_NAMES,
    get_session,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_com():
    """Mock win32com.client and pythoncom so tests run without Windows."""
    mock_app = MagicMock()
    mock_app.Projects.Count = 1
    mock_app.ActiveProject.FullName = r"C:\test\fixture.mpp"
    mock_app.Visible = True

    with patch.dict("sys.modules", {
        "win32com": MagicMock(),
        "win32com.client": MagicMock(),
        "pythoncom": MagicMock(),
    }):
        # Make Dispatch and GetActiveObject return our mock app
        import win32com.client
        win32com.client.Dispatch.return_value = mock_app
        win32com.client.GetActiveObject.return_value = mock_app
        yield mock_app


@pytest.fixture
def fresh_session():
    """A fresh ProjectSession with no COM connection."""
    return ProjectSession(headless=True)


# ---------------------------------------------------------------------------
# State lifecycle tests
# ---------------------------------------------------------------------------

class TestSessionLifecycle:
    """Test attach/detach state transitions."""

    def test_initial_state_is_detached(self, fresh_session):
        assert fresh_session.state == SessionState.DETACHED
        assert not fresh_session.is_attached

    def test_attach_transitions_to_attached(self, fresh_session, mock_com):
        with patch(
            "src.project_session._find_existing_project_processes",
            return_value=[],
        ):
            fresh_session.attach()
            assert fresh_session.state == SessionState.ATTACHED
            assert fresh_session.is_attached

    def test_detach_transitions_to_detached(self, fresh_session, mock_com):
        with patch(
            "src.project_session._find_existing_project_processes",
            return_value=[],
        ):
            fresh_session.attach()
            fresh_session.detach()
            assert fresh_session.state == SessionState.DETACHED
            assert not fresh_session.is_attached

    def test_detach_waits_for_the_process_it_launched(self, mock_com):
        """After Quit, detach returns only once the launched WINPROJ.EXE has exited."""
        session = ProjectSession(quit_on_detach=True)
        with patch("src.project_session._find_existing_project_processes", side_effect=[[], [4321]]), \
                patch("src.session_lifecycle.wait_for_exit") as wait:
            session.attach()
            session.detach()
        mock_com.Quit.assert_called_once_with(0)
        wait.assert_called_once_with({4321})

    def test_detach_does_not_wait_for_an_adopted_instance(self, mock_com):
        session = ProjectSession(quit_on_detach=True)
        with patch("src.project_session._find_existing_project_processes", return_value=[1234]), \
                patch("src.session_lifecycle.wait_for_exit") as wait:
            session.attach()
            session.detach()
        mock_com.Quit.assert_not_called()
        wait.assert_not_called()

    def test_double_attach_is_noop(self, fresh_session, mock_com):
        with patch(
            "src.project_session._find_existing_project_processes",
            return_value=[],
        ):
            fresh_session.attach()
            fresh_session.attach()  # should warn but not error
            assert fresh_session.state == SessionState.ATTACHED

    def test_double_detach_is_noop(self, fresh_session, mock_com):
        with patch(
            "src.project_session._find_existing_project_processes",
            return_value=[],
        ):
            fresh_session.attach()
            fresh_session.detach()
            fresh_session.detach()  # should warn but not error
            assert fresh_session.state == SessionState.DETACHED

    def test_app_raises_when_detached(self, fresh_session):
        with pytest.raises(RuntimeError, match="not attached"):
            _ = fresh_session.app


class TestCollisionDetection:
    """Test behavior when Project is already running."""

    def test_refuses_when_existing_and_not_allowed(self, mock_com):
        session = ProjectSession(allow_attach_existing=False)
        with patch(
            "src.project_session._find_existing_project_processes",
            return_value=[1234],
        ):
            with pytest.raises(RuntimeError, match="already running"):
                session.attach()
            assert session.state == SessionState.ERROR

    def test_attaches_when_existing_and_allowed(self, mock_com):
        session = ProjectSession(allow_attach_existing=True)
        with patch(
            "src.project_session._find_existing_project_processes",
            return_value=[1234],
        ):
            session.attach()
            assert session.is_attached
            assert not session._we_launched

    def test_launches_when_no_existing(self, mock_com):
        session = ProjectSession()
        with patch(
            "src.project_session._find_existing_project_processes",
            return_value=[],
        ):
            session.attach()
            assert session.is_attached
            assert session._we_launched


class TestSessionInfo:
    """Test the session info snapshot."""

    def test_info_when_detached(self, fresh_session):
        info = fresh_session.get_info()
        assert info.state == "detached"
        assert info.owner_pid == os.getpid()
        assert info.project_path is None

    def test_info_when_attached(self, mock_com):
        session = ProjectSession()
        with patch(
            "src.project_session._find_existing_project_processes",
            return_value=[],
        ):
            session.attach()
            info = session.get_info()
            assert info.state == "attached"
            assert info.owner_pid == os.getpid()
            assert info.we_launched is True


class TestContextManager:
    """Test the with-statement support."""

    def test_context_manager_attaches_and_detaches(self, mock_com):
        with patch(
            "src.project_session._find_existing_project_processes",
            return_value=[],
        ):
            session = ProjectSession()
            with session:
                assert session.is_attached
            assert not session.is_attached


class TestConfigure:
    """Test the configure() method (review fix #4)."""

    def test_configure_updates_headless(self, fresh_session):
        fresh_session.configure(headless=False)
        assert fresh_session._headless is False

    def test_configure_updates_allow_attach(self, fresh_session):
        fresh_session.configure(allow_attach_existing=False)
        assert fresh_session._allow_attach_existing is False

    def test_configure_updates_quit_on_detach(self, fresh_session):
        fresh_session.configure(quit_on_detach=True)
        assert fresh_session._quit_on_detach is True

    def test_configure_rejects_while_attached(self, mock_com):
        session = ProjectSession()
        with patch(
            "src.project_session._find_existing_project_processes",
            return_value=[],
        ):
            session.attach()
            with pytest.raises(RuntimeError, match="Cannot reconfigure"):
                session.configure(headless=False)
            session.detach()

    def test_configure_partial_update(self, fresh_session):
        """Only passed kwargs are changed; others stay."""
        original_headless = fresh_session._headless
        fresh_session.configure(quit_on_detach=True)
        assert fresh_session._headless == original_headless
        assert fresh_session._quit_on_detach is True


class TestProcessNames:
    """Verify process name constants (review fix #1 and #7)."""

    def test_no_publisher_in_process_names(self):
        """MSPUB.EXE is Publisher, not Project — must not be present."""
        for name in PROJECT_PROCESS_NAMES:
            assert name != "MSPUB.EXE", "MSPUB.EXE is Publisher, not Project"

    def test_winproj_in_process_names(self):
        assert "WINPROJ.EXE" in PROJECT_PROCESS_NAMES


class TestSingleton:
    """Test the module-level singleton."""

    def test_get_session_returns_same_instance(self):
        import src.project_session as mod
        mod._session = None  # Reset
        s1 = get_session()
        s2 = get_session()
        assert s1 is s2
        mod._session = None  # Cleanup
