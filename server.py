"""
MS Project MCP Server
Controls local Microsoft Project via COM automation.
Install: pip install -r requirements.txt
Run:     python server.py
Register in claude_desktop_config.json (see bottom of file).

This module only wires the server together: it creates the FastMCP instance, registers the core
tools from src/tools/ and the optional hardening tools from src/, then applies schema stripping
and ToolAnnotations over everything registered.
"""

import importlib
import logging
import os
import sys
from mcp.server.fastmcp import FastMCP

# The src/ package lives next to this file.
_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

# The instructions string must exist before the FastMCP instance is created.
try:
    from src.tool_guide import SERVER_INSTRUCTIONS as _SERVER_INSTRUCTIONS
except Exception:
    _SERVER_INSTRUCTIONS = ""

from src.guards import _record_load_error, get_session  # noqa: E402

mcp = FastMCP("MS Project", instructions=_SERVER_INSTRUCTIONS)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Core tools
# ---------------------------------------------------------------------------

CORE_TOOL_MODULES = (
    ("src.tools.project", "register_project_tools"),
    ("src.tools.multiproject", "register_multiproject_tools"),
    ("src.tools.task_query", "register_task_query_tools"),
    ("src.tools.task_filter", "register_task_filter_tools"),
    ("src.tools.task_write", "register_task_write_tools"),
    ("src.tools.task_structure", "register_task_structure_tools"),
    ("src.tools.task_placement", "register_task_placement_tools"),
    ("src.tools.scheduling", "register_scheduling_tools"),
    ("src.tools.dependencies", "register_dependencies_tools"),
    ("src.tools.resources", "register_resources_tools"),
    ("src.tools.resource_planning", "register_resource_planning_tools"),
    ("src.tools.calendars", "register_calendars_tools"),
    ("src.tools.calendar_exceptions", "register_calendar_exceptions_tools"),
    ("src.tools.custom_fields", "register_custom_fields_tools"),
    ("src.tools.snapshots", "register_snapshots_tools"),
    ("src.tools.baselines", "register_baselines_tools"),
    ("src.tools.progress", "register_progress_tools"),
    ("src.tools.cost", "register_cost_tools"),
    ("src.tools.schedule_analysis", "register_schedule_analysis_tools"),
    ("src.tools.milestones", "register_milestone_tools"),
    ("src.tools.critical_path", "register_critical_path_tools"),
    ("src.tools.what_if", "register_what_if_tools"),
    ("src.tools.meta", "register_meta_tools"),
)


def _register_core_tools():
    """Register the core tools. Unlike the hardening modules, a failure here is fatal and stops startup."""
    for module_name, register_name in CORE_TOOL_MODULES:
        getattr(importlib.import_module(module_name), register_name)(mcp)


_register_core_tools()

# ---------------------------------------------------------------------------
# Hardening tools
# ---------------------------------------------------------------------------

# src/verify_write.py is a library for mutating tools, not a tool module.
HARDENING_TOOL_MODULES = (
    ("src.session_tools", "register_session_tools"),
    ("src.identity_tools", "register_identity_tools"),
    ("src.calc_tools", "register_calc_tools"),
    ("src.store_tools", "register_store_tools"),
    ("src.ui_tools", "register_ui_tools"),
    ("src.bulk_tools", "register_bulk_tools"),
    ("src.mpxj_tools", "register_mpxj_tools"),          # mpxj fast-read path
)


def _session_active_project():
    """TaskStore's project source: the active project of the ProjectSession."""
    if get_session is None:
        raise RuntimeError(
            "ProjectSession is unavailable. See hardening_tool_errors in health_check."
        )
    return get_session().app.ActiveProject


def _register_hardening_tools():
    """
    Register each hardening module's tools next to the legacy tools. A module that
    fails to load is logged and recorded in HARDENING_LOAD_ERRORS; the others still load.
    """
    for module_name, register_name in HARDENING_TOOL_MODULES:
        try:
            getattr(importlib.import_module(module_name), register_name)(mcp)
        except Exception as e:
            _record_load_error(module_name, e)
    try:
        from src.task_store import init_store
        init_store(_session_active_project)
    except Exception as e:
        _record_load_error("src.task_store", e)


_register_hardening_tools()

# get_tool_guide meta-tool.
try:
    from src.tool_guide import register_tool_guide
    register_tool_guide(mcp)
except Exception as _e:
    logger.warning("tool_guide registration failed: %s", _e)

# ---------------------------------------------------------------------------
# Schema size reduction: strip decorative "title" from tool schemas.
# Must run AFTER all tools are registered (including hardening modules above).
# ---------------------------------------------------------------------------
try:
    from src.schema_strip import strip_schema_titles
    _schema_stripped = strip_schema_titles(mcp)
except Exception as _e:
    logger.warning("Schema title stripping failed (harmless): %s", _e)
    _schema_stripped = 0

# ---------------------------------------------------------------------------
# ToolAnnotations: classify all tools with MCP annotations.
# Must run AFTER all tools are registered (including hardening modules above).
# ---------------------------------------------------------------------------
try:
    from src.annotations import apply_annotations
    _tools_annotated = apply_annotations(mcp)
except Exception as _e:
    logger.warning("ToolAnnotations application failed (harmless): %s", _e)
    _tools_annotated = 0

# ---------------------------------------------------------------------------
# Guardrails: strict args, dry-run gate, project_id guard, error contract,
# modal-dialog watchdog. Must run AFTER annotations (it reads readOnlyHint).
# ---------------------------------------------------------------------------
from src.tool_guardrails import apply_guardrails  # noqa: E402
_tools_guarded = apply_guardrails(mcp)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Entry point for console_scripts and direct execution."""
    print("Starting MS Project MCP Server...", file=sys.stderr)
    print("MS Project must be running with a file open before using tools.", file=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# REGISTRATION — add this to claude_desktop_config.json:
#
# {
#   "mcpServers": {
#     "msproject": {
#       "command": "python",
#       "args": ["/path/to/msproject/server.py"]
#     }
#   }
# }
# ---------------------------------------------------------------------------
