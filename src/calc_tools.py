"""
WP-4: MCP tools for calculation policy control.

Registers tools that let the LLM orchestrator:
- Query the current calculation mode
- Switch between automatic and manual calculation
- Trigger an explicit full recalculation
"""

import logging
from .calc_policy import (
    CalcMode,
    get_calc_mode,
    get_calc_state,
    set_calc_mode,
    calculate_project,
)

logger = logging.getLogger(__name__)


def register_calc_tools(mcp):
    """Register calculation policy MCP tools."""

    @mcp.tool()
    def get_calculation_mode() -> dict:
        """
        Get the current MS Project calculation mode.

        Returns the mode ("automatic" or "manual") and the raw
        COM enum value.
        """
        from .project_session import get_session
        session = get_session()
        app = session._app
        if app is None:
            return {"error": "No active session. Call session_attach first."}
        state = get_calc_state(app)
        return state.to_dict()

    @mcp.tool()
    def set_calculation_mode(mode: str) -> dict:
        """
        Set the MS Project calculation mode.

        Args:
            mode: "automatic" or "manual"

        Returns:
            Previous and new mode information.
        """
        from .project_session import get_session
        session = get_session()
        app = session._app
        if app is None:
            return {"error": "No active session. Call session_attach first."}

        mode_lower = mode.strip().lower()
        if mode_lower not in ("automatic", "manual"):
            return {
                "error": f"Invalid mode '{mode}'. Use 'automatic' or 'manual'."
            }

        target = (
            CalcMode.AUTOMATIC if mode_lower == "automatic"
            else CalcMode.MANUAL
        )
        try:
            previous = set_calc_mode(app, target)
            return {
                "previous_mode": previous.name.lower(),
                "new_mode": target.name.lower(),
                "changed": previous != target,
            }
        except RuntimeError as e:
            return {"error": str(e)}

    @mcp.tool()
    def calculate_now(scope: str = "all") -> dict:
        """
        Trigger an explicit recalculation of the project schedule.

        Use after batch operations performed with calculation set to
        manual mode, or any time you need to force a fresh schedule
        calculation.

        Args:
            scope: "all" to recalculate all open projects, or
                   "active" to recalculate only the active project.

        Returns:
            Dict with recalculated (bool), scope, and error fields.
        """
        from .project_session import get_session
        session = get_session()
        app = session._app
        if app is None:
            return {"error": "No active session. Call session_attach first."}

        if scope not in ("all", "active"):
            return {
                "error": f"Invalid scope '{scope}'. Use 'all' or 'active'."
            }

        project = None
        if scope == "active":
            try:
                project = app.ActiveProject
            except Exception as e:
                logger.warning("Could not get ActiveProject: %s", e)
                return {"error": f"No active project: {e}"}

        return calculate_project(app, project=project)
