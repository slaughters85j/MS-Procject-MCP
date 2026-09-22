"""
Server diagnostics.
"""

import json

from .. import guards
from ..com_helpers import _find_app
from ..guards import get_safe_root, is_dry_run


def register_meta_tools(mcp):
    """Register the meta tools on the FastMCP instance."""

    @mcp.tool()
    def health_check() -> str:
        """
        Lightweight connectivity test. Returns MS Project version, whether a project
        is open, and basic project info if available. Lists any hardening tool
        modules that failed to load under "hardening_tool_errors".
        """
        app = _find_app()
        if app is None:
            result = {"status": "disconnected", "error": "MS Project is not running."}
        else:
            result = {
                "status":  "connected",
                "version": str(app.Version),
            }
            if app.Projects.Count > 0:
                proj = app.ActiveProject
                result["project_open"] = True
                result["project_name"] = proj.Name
                result["task_count"]   = proj.Tasks.Count
            else:
                result["project_open"] = False

        if guards.HARDENING_LOAD_ERRORS:
            result["hardening_tool_errors"] = guards.HARDENING_LOAD_ERRORS

        # Safety guard status
        result["safe_root"] = get_safe_root()
        result["dry_run"] = is_dry_run()

        return json.dumps(result, indent=2)
