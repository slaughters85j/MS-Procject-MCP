"""
MCP tools for UI mode control.

Registers tools that let the LLM orchestrator:
- Read the effective UI mode (invisible / locked / open)
- Switch the UI mode
- Read the full UI lock state, including restore failures

NOTE: Testing against live MS Project remains required.
"""

import logging

# Imported as a module: the tool names below match the function names in
# ui_lock, so a direct import would be shadowed and the tools would recurse.
from . import ui_lock as ui

logger = logging.getLogger(__name__)

NO_SESSION_ERROR = "No active session. Call session_attach first."


def _get_app():
    """Return the session's COM Application, or None if not attached."""
    from .project_session import get_session
    return get_session()._app


def register_ui_tools(mcp):
    """Register UI mode MCP tools."""

    @mcp.tool()
    def get_ui_mode() -> dict:
        """
        Get how tool calls are protected from the MS Project window.

        Returns:
            Dict with mode ("invisible", "locked", or "open"), lock_active
            (bool), and errors (restore failures or a frozen window), or an
            "error" key on failure.
        """
        app = _get_app()
        if app is None:
            return {"error": NO_SESSION_ERROR}
        try:
            state = ui.get_ui_state(app)
        except RuntimeError as e:
            return {"error": str(e)}
        return {
            "mode": state.mode,
            "lock_active": state.locked_at is not None,
            "errors": list(state.errors),
        }

    @mcp.tool()
    def set_ui_mode(mode: str) -> dict:
        """
        Set how tool calls are protected from the MS Project window.

        Args:
            mode: "invisible" (hide Project; safest for unattended work),
                  "locked" (visible; screen updates frozen during each
                  tool call; does NOT block mouse or keyboard input), or
                  "open" (visible; no protection).

        Returns:
            Dict with previous_mode, new_mode, and changed, or an "error"
            key on failure.
        """
        app = _get_app()
        if app is None:
            return {"error": NO_SESSION_ERROR}
        valid = ", ".join(m.value for m in ui.UIMode)
        invalid = {"error": f"Invalid mode {mode!r}. Use one of: {valid}."}
        if not isinstance(mode, str):
            return invalid
        try:
            target = ui.UIMode(mode.strip().lower())
        except ValueError:
            return invalid
        try:
            previous = ui.set_ui_mode(app, target)
        except RuntimeError as e:
            return {"error": str(e)}
        return {
            "previous_mode": previous.value,
            "new_mode": target.value,
            "changed": previous != target,
        }

    @mcp.tool()
    def get_ui_state() -> dict:
        """
        Get the full UI lock state for diagnostics.

        Returns:
            Dict with mode, screen_updating_was, locked_at, and errors
            (restore failures or a frozen window), or an "error" key if
            the state could not be read.
        """
        app = _get_app()
        if app is None:
            return {"error": NO_SESSION_ERROR}
        try:
            return ui.get_ui_state(app).to_dict()
        except RuntimeError as e:
            return {"error": str(e)}
