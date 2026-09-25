"""
Modal-dialog watchdog for tool calls.

A COM call that makes MS Project raise a modal dialog (Planning Wizard, Compatibility Checker,
Project Information, message boxes) blocks until a human answers it, which hangs the MCP server
and locks the object model. While a tool runs, this watchdog checks Project's top-level windows
after a grace period, records the text of any dialog it finds and presses its safe choice
(the "Cancel. Do not ..." option, then Cancel/No, falling back to OK), so the COM call returns.
"""

import logging
import threading

logger = logging.getLogger(__name__)

_MAIN_CLASSES = ("JWinproj-WhimperMainClass", "MS-SDIa")
_CANCEL_TEXTS = ("Cancel", "No")


def _dialog_windows():
    """Visible top-level windows owned by WINPROJ.EXE other than its main and document frames."""
    import win32gui
    import win32process
    from .project_session import _find_existing_project_processes
    pids = set(_find_existing_project_processes())
    found = []

    def visit(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        if win32process.GetWindowThreadProcessId(hwnd)[1] not in pids:
            return
        if win32gui.GetClassName(hwnd) in _MAIN_CLASSES:
            return
        found.append(hwnd)
    win32gui.EnumWindows(visit, None)
    return found


def dismiss_dialogs():
    """Cancel every open Project dialog. Returns a description of each one dismissed."""
    import win32api
    import win32con
    import win32gui
    dismissed = []
    for hwnd in _dialog_windows():
        kids = []
        win32gui.EnumChildWindows(
            hwnd, lambda c, _: kids.append((c, win32gui.GetClassName(c), win32gui.GetWindowText(c))), None)
        buttons = [(c, text.replace("&", "")) for c, cls, text in kids if cls == "Button" and text]
        texts = [text for _, cls, text in kids if cls == "Static" and text]
        radio = next((c for c, text in buttons if text.lower().startswith("cancel.")), None)
        if radio:
            win32gui.SendMessage(radio, win32con.BM_CLICK, 0, 0)
            target = next((c for c, text in buttons if text == "OK"), None)
        else:
            target = (next((c for c, text in buttons if text in _CANCEL_TEXTS), None)
                      or next((c for c, text in buttons if text == "OK"), None))
        if target:
            win32api.PostMessage(target, win32con.BM_CLICK, 0, 0)
            dismissed.append(f"{win32gui.GetWindowText(hwnd)}: {' '.join(texts)[:300]}")
    return dismissed


class ModalWatchdog:
    """Context manager: while active, dismiss Project dialogs that stay open past `grace` seconds."""

    def __init__(self, grace=8.0, interval=2.0):
        self.grace = grace
        self.interval = interval
        self.dismissed = []
        self._stop = threading.Event()
        self._thread = None

    def _run(self):
        if self._stop.wait(self.grace):
            return
        while not self._stop.is_set():
            try:
                self.dismissed.extend(dismiss_dialogs())
            except Exception as e:  # never let the watchdog kill the server
                logger.debug("modal watchdog scan failed: %s", e)
            self._stop.wait(self.interval)

    def __enter__(self):
        self._thread = threading.Thread(target=self._run, name="modal-watchdog", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        return False
