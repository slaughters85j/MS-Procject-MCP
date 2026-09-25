"""
Launching a private MS Project for the integration tests, probing availability once per
session, and locating the generated .mpp fixtures.
"""

import logging
import os
import subprocess
import sys
import time

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Platform gate — skip entire module on non-Windows
# ---------------------------------------------------------------------------

IS_WINDOWS = sys.platform == "win32"


def _project_already_running():
    """True if WINPROJ.EXE is running. Dispatch would attach to that (the user's) instance,
    and these fixtures hide, close and quit the instance they get, so never run then."""
    try:
        result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq WINPROJ.EXE"],
                                capture_output=True, text=True, timeout=5)
        return "WINPROJ.EXE" in result.stdout
    except Exception:
        return False


def _launch_project(attempts=3, delay=2.0):
    """
    Start a private MS Project instance. DispatchEx asks COM for a new server process;
    cold activation can fail transiently with CO_E_SERVER_EXEC_FAILURE, so retry with backoff.
    """
    import win32com.client
    last = None
    for attempt in range(attempts):
        try:
            return win32com.client.DispatchEx("MSProject.Application")
        except Exception as e:  # pywintypes.com_error
            last = e
            time.sleep(delay * (attempt + 1))
    raise last

def _check_project_available():
    """
    Probe whether MS Project COM automation works.

    Returns (available: bool, reason: str).
    Does NOT leave a running instance — quits immediately after probe.
    """
    if not IS_WINDOWS:
        return False, "Not running on Windows"

    try:
        import win32com.client
        import pythoncom
    except ImportError:
        return False, "pywin32 not installed (pip install pywin32)"

    if _project_already_running():
        return False, ("MS Project is already running. Integration tests start, hide and quit their own "
                       "instance, so close Project first (they will not touch a running session).")

    try:
        pythoncom.CoInitialize()
        app = _launch_project()
        app.Visible = False
        app.DisplayAlerts = False
        # Quick sanity: can we create a blank project?
        app.FileNew(SummaryInfo=False)
        count = app.Projects.Count
        app.FileClose(Save=0)
        app.Quit(0)  # 0 = pjDoNotSave
        del app
        pythoncom.CoUninitialize()
        if count < 1:
            return False, "Project launched but FileNew produced no project"
        return True, "OK"
    except Exception as e:
        return False, f"COM probe failed: {type(e).__name__}: {e}"


# Cache the probe result so we only launch/quit once per session
_project_available = None
_project_skip_reason = None


def _ensure_probed():
    global _project_available, _project_skip_reason
    if _project_available is None:
        _project_available, _project_skip_reason = _check_project_available()


# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")
GENERATED_FIXTURES_DIR = os.path.join(FIXTURES_DIR, "generated")


def _fixture_path(name: str) -> str:
    """
    Resolve a fixture .mpp by name.

    Looks in generated/ first (created by generate_fixtures.py on Windows),
    then in the fixtures/ root (for hand-created or checked-in files).
    """
    generated = os.path.join(GENERATED_FIXTURES_DIR, name)
    if os.path.isfile(generated):
        return generated
    root = os.path.join(FIXTURES_DIR, name)
    if os.path.isfile(root):
        return root
    raise FileNotFoundError(
        f"Fixture '{name}' not found in {GENERATED_FIXTURES_DIR} or "
        f"{FIXTURES_DIR}. Run 'python tests/fixtures/generate_fixtures.py' "
        f"on a Windows machine with MS Project to create fixtures."
    )


def probe_state():
    """(available, reason) for MS Project automation, probed once per test session."""
    _ensure_probed()
    return _project_available, _project_skip_reason
