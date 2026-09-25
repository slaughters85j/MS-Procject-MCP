"""
Integration test harness — conftest.py

Pytest fixtures that launch MS Project via COM, open fixture .mpp files,
and tear down cleanly. Each test gets a fresh Project instance (no
cross-test contamination).

REQUIREMENTS:
  - Windows 10/11 with MS Project 2016+ installed and licensed
  - Python 3.10+ with pywin32 (pip install pywin32)
  - Run: pytest tests/integration/ -v

SKIP LOGIC:
  Tests auto-skip on non-Windows platforms or when Project is not installed.
  The skip is at the session level so you get one clear message, not 50.
"""

import os
import sys
import time
import shutil
import logging
import subprocess
import pytest

logger = logging.getLogger(__name__)

from ._project_launch import (  # noqa: E402
    _launch_project, _project_already_running, probe_state, _fixture_path,
)


# ---------------------------------------------------------------------------
# Session-scoped skip
# ---------------------------------------------------------------------------

def pytest_collection_modifyitems(config, items):
    """Skip all integration tests if Project is not available."""
    available, reason = probe_state()
    if available:
        return

    skip_marker = pytest.mark.skip(
        reason=f"MS Project not available: {reason}"
    )
    for item in items:
        # Only skip tests in this integration directory
        if "integration" in str(item.fspath):
            item.add_marker(skip_marker)


@pytest.fixture(autouse=True)
def _release_server_launched_project():
    """
    Scenario tests drive the server's tools, which launch (and keep attached) their own hidden
    Project. Quit it after each test so the next test starts clean instead of seeing
    "Project already running". Instances the server did not launch are never touched.
    """
    yield
    try:
        from src.project_session import get_session
        session = get_session()
        if session.is_attached and session._we_launched:
            app = session.app
            while app.Projects.Count > 0:
                app.FileCloseEx(0)  # pjDoNotSave: scenario projects are scratch
            app.Quit(0)  # configure() cannot change quit_on_detach while attached
            session.detach()
            # Wait for WINPROJ.EXE to exit, or the next test's auto-attach would find the dying
            # process, adopt it as "not ours", and never quit it.
            from src.project_session import _find_existing_project_processes
            deadline = time.time() + 20
            while _find_existing_project_processes() and time.time() < deadline:
                time.sleep(0.5)
    except Exception as e:
        logger.warning("Releasing server-launched Project failed: %s", e)


# ---------------------------------------------------------------------------
# Core fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def com_init():
    """Initialize COM for the current thread. Balanced teardown."""
    import pythoncom
    pythoncom.CoInitialize()
    yield
    pythoncom.CoUninitialize()


@pytest.fixture(scope="function")
def project_app(com_init):
    """
    Launch a fresh, invisible MS Project instance for one test.

    Yields the COM Application object. Tears down by:
    1. Closing all open projects without saving
    2. Quitting Project
    3. Releasing the COM reference

    If teardown fails, logs the error but does not raise — we don't
    want teardown failures to mask test failures.
    """
    if _project_already_running():
        pytest.skip("MS Project is already running; refusing to attach to (and then quit) that instance.")
    app = _launch_project()
    app.Visible = False
    app.DisplayAlerts = False
    logger.info("Launched MS Project (PID-scoped, invisible)")

    yield app

    # --- Teardown ---
    try:
        # Close all projects without saving
        while app.Projects.Count > 0:
            try:
                app.FileClose(Save=0)
            except Exception as e:
                logger.warning("FileClose during teardown: %s", e)
                break
    except Exception as e:
        logger.warning("Projects.Count during teardown: %s", e)

    try:
        app.Quit(0)  # pjDoNotSave
    except Exception as e:
        logger.warning("Quit during teardown: %s", e)

    try:
        del app
    except Exception:
        pass

    # Brief pause to let the process fully exit
    time.sleep(0.5)

    # Hard-kill fallback: if Quit didn't work, force-terminate WINPROJ.EXE
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq WINPROJ.EXE"],
            capture_output=True, text=True, timeout=5
        )
        if "WINPROJ.EXE" in result.stdout:
            logger.warning("WINPROJ.EXE still running after Quit — force-killing")
            subprocess.run(
                ["taskkill", "/IM", "WINPROJ.EXE", "/F"],
                capture_output=True, timeout=5
            )
            time.sleep(0.5)
    except Exception as e:
        logger.warning("Hard-kill check failed (non-Windows?): %s", e)

    logger.info("MS Project teardown complete")


@pytest.fixture(scope="function")
def temp_mpp(project_app, tmp_path):
    """
    Open a fixture .mpp in a temp copy so the original is never modified.

    Uses the 'basic_project.mpp' fixture. If it doesn't exist yet,
    creates a minimal project on-the-fly via COM (self-bootstrapping).

    Yields (app, project, temp_file_path).
    """
    app = project_app

    # Try to use the generated fixture
    try:
        src = _fixture_path("basic_project.mpp")
        dst = os.path.join(str(tmp_path), "test_project.mpp")
        shutil.copy2(src, dst)
        app.FileOpen(dst)
    except FileNotFoundError:
        # Self-bootstrap: create a minimal project on-the-fly
        logger.info("No fixture found — creating minimal project on-the-fly")
        app.FileNew(SummaryInfo=False)
        proj = app.ActiveProject
        proj.Title = "Test Fixture (auto-generated)"

        # Add a handful of tasks for tests to work with
        t1 = proj.Tasks.Add("Summary Phase")
        t1.OutlineLevel = 1

        t2 = proj.Tasks.Add("Task Alpha")
        t2.OutlineLevel = 2
        t2.Duration = int(proj.HoursPerDay * 60) * 3  # 3 days
        t2.Text1 = "Green"

        t3 = proj.Tasks.Add("Task Beta")
        t3.OutlineLevel = 2
        t3.Duration = int(proj.HoursPerDay * 60) * 5  # 5 days
        t3.Text1 = "Red"

        t4 = proj.Tasks.Add("Milestone")
        t4.OutlineLevel = 2
        t4.Duration = 0
        t4.Milestone = True

        # Save to temp path
        dst = os.path.join(str(tmp_path), "test_project.mpp")
        app.FileSaveAs(Name=dst, Format=0)

    proj = app.ActiveProject
    yield app, proj, dst


@pytest.fixture(scope="function")
def session_fixture(com_init):
    """
    A fresh ProjectSession wired for integration testing.

    Attaches with headless=True, quit_on_detach=True.
    Detaches in teardown — Project quits automatically.
    """
    # Add project root to path so src imports work
    project_root = os.path.join(os.path.dirname(__file__), "..", "..")
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from src.project_session import ProjectSession

    session = ProjectSession(
        headless=True,
        allow_attach_existing=False,
        quit_on_detach=True,
    )
    session.attach()
    yield session
    session.detach()
    time.sleep(0.5)


@pytest.fixture(scope="function")
def temp_mpp_via_session(session_fixture, tmp_path):
    """
    Open a temp .mpp through the ProjectSession (exercises the full attach, open, and detach path).

    Creates a minimal project on-the-fly, saves to tmp_path.
    Yields (session, app, project, temp_file_path).
    """
    session = session_fixture
    app = session.app

    app.FileNew(SummaryInfo=False)
    proj = app.ActiveProject
    proj.Title = "Session Test"

    t1 = proj.Tasks.Add("Phase 1")
    t1.OutlineLevel = 1
    t2 = proj.Tasks.Add("Work Item A")
    t2.OutlineLevel = 2
    t2.Duration = int(proj.HoursPerDay * 60) * 2
    t3 = proj.Tasks.Add("Work Item B")
    t3.OutlineLevel = 2
    t3.Duration = int(proj.HoursPerDay * 60) * 4
    t3.Text1 = "Amber"

    dst = os.path.join(str(tmp_path), "session_test.mpp")
    app.FileSaveAs(Name=dst, Format=0)

    yield session, app, proj, dst


# ---------------------------------------------------------------------------
# Shared test helpers — eliminate DRY violations across test files
# ---------------------------------------------------------------------------

def live_task_count(proj):
    """Count non-None tasks in a project."""
    return sum(1 for t in proj.Tasks if t is not None)


def find_task_by_uid(proj, uid):
    """Find a task by UniqueID, returning None if not found."""
    for t in proj.Tasks:
        if t is not None and t.UniqueID == uid:
            return t
    return None

