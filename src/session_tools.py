"""
Session management MCP tools.

Exposes attach, detach, and session_info as MCP tools.
These are registered on the FastMCP instance in server.py.

NOTE: Testing remains required — MS Project not available on build machine.
"""

import logging
from dataclasses import asdict

from .project_session import get_session

logger = logging.getLogger(__name__)


def register_session_tools(mcp):
    """Register session lifecycle tools on the given FastMCP instance."""

    @mcp.tool()
    def session_attach(
        headless: bool = True,
        allow_attach_existing: bool = True,
    ) -> dict:
        """
        Attach to MS Project via COM.

        Creates or connects to a single Project.Application COM instance.
        Refuses if another COM client is already bound (unless
        allow_attach_existing is True).

        Args:
            headless: Run Project with Visible=False (default True).
            allow_attach_existing: Attach to already-running Project
                instead of refusing (default True).

        Returns:
            Session info dict with state, owner PID, project path.
        """
        session = get_session()

        # Apply configuration via public API before attach
        session.configure(
            headless=headless,
            allow_attach_existing=allow_attach_existing,
        )

        session.attach()
        info = session.get_info()
        return asdict(info)

    @mcp.tool()
    def session_detach(quit_project: bool = False) -> dict:
        """
        Detach from MS Project, releasing the COM connection.

        Args:
            quit_project: If True AND we launched Project, quit the app.
        """
        session = get_session()
        if quit_project:
            session.configure(quit_on_detach=True)
        session.detach()
        return {"status": "detached", "quit_requested": quit_project}

    @mcp.tool()
    def session_info() -> dict:
        """
        Return current session state.

        Returns:
            Dict with state, owner_pid, project_path, project_count,
            we_launched, and com_class.
        """
        session = get_session()
        info = session.get_info()
        return asdict(info)
