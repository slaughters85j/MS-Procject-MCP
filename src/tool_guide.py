"""
Server Instructions + Tool Guide

Provides:
  1. SERVER_INSTRUCTIONS — text passed to FastMCP(instructions=...) so LLM
     clients receive batching rules and environment guidance at session init.
  2. get_tool_guide() — meta-tool returning a categorized tool inventory
     organized by architectural concern, not by 4nswer's original categories.

Adapted from 4nswer fork's SERVER_INSTRUCTIONS and get_tool_guide(). Categories
reflect the hardening modules and bulk_ops design.
"""

import json
import logging

logger = logging.getLogger(__name__)

SERVER_INSTRUCTIONS = """\
Controls Microsoft Project via COM automation. MS Project must be running \
with a project file open.

BATCHING RULE: When operating on 2+ tasks/links/assignments in a single \
intent, ALWAYS call the matching bulk_* tool once. Never loop the single-item \
tool. Bulk tools suspend auto-recalculation and use one save round-trip, \
making them both faster and safer.

Single-to-Bulk pairs:
  add_task              -> bulk_add_tasks
  update_task           -> bulk_update_tasks (or bulk_update_rag for RAG only)
  add_predecessor       -> bulk_add_predecessors
  remove_predecessor    -> bulk_remove_predecessors
  set_task_mode         -> bulk_set_task_mode
  set_constraint        -> bulk_set_constraints
  set_deadline          -> bulk_set_deadlines
  set_task_active       -> bulk_set_task_active
  update_custom_fields  -> bulk_update_custom_fields
  assign_resource       -> bulk_assign_resources

After any bulk manual-schedule change, call calculate_project to refresh dates.
Use dry_run_bulk_update to preview bulk_update_tasks changes before applying.

FAST READ PATH (mpxj):
  mpxj_read_* tools read .mpp files from DISK — 20-30x faster than COM.
  They do NOT require MS Project to be running. Cross-platform (Mac/Linux/Win).
  IMPORTANT: They read the SAVED file. Unsaved changes are NOT reflected.
  For live COM state, use get_tasks / get_resources / get_project_info.
  Install: pip install 'msproject-mcp[mpxj]' (requires JDK/JRE).

ENVIRONMENT:
  MSPROJECT_SAFE_ROOT   Directory all file tools are confined to (required).
  MSPROJECT_DRY_RUN=1   Read/preview-only mode; mutations logged but not applied.

HARDENING:
  ProjectSession manages COM lifecycle. Use session_info to check state.
  ProjectIdentity provides canonical project hash and path.
  verify_write re-reads fields after every mutation for drift detection.
  CalcPolicy controls recalculation timing (deferred_calc).
  TaskStore resolves tasks by UniqueID with stale-proxy detection.
  UILock manages ScreenUpdating and StatusBar for batch operations.
  bulk_ops supports dry-run/apply with per-item verification.

Call get_tool_guide() for the full tool category map and efficiency rules.\
"""


# The tool guide payload — static dict, not rebuilt per call.
_TOOL_GUIDE = {
    "efficiency_rules": [
        "Use bulk_* tools when operating on 2+ items — they suspend auto-recalculation and batch saves.",
        "Call calculate_project after bulk manual-schedule changes if auto-calc was suspended.",
        "Use dry_run_bulk_update to preview changes safely before bulk_update_tasks.",
        "Use undo_last (up to 10) as a safety net after any bulk mutation.",
        "MSPROJECT_SAFE_ROOT must be set before any file-taking tool will run.",
        "Set MSPROJECT_DRY_RUN=1 for read/preview-only mode.",
        "Check health_check to verify which hardening modules loaded successfully.",
    ],
    "bulk_pairs": {
        "create_tasks":         {"single": "add_task",             "bulk": "bulk_add_tasks"},
        "update_tasks":         {"single": "update_task",          "bulk": "bulk_update_tasks"},
        "update_rag":           {"single": "update_task",          "bulk": "bulk_update_rag"},
        "add_links":            {"single": "add_predecessor",      "bulk": "bulk_add_predecessors"},
        "set_mode":             {"single": "set_task_mode",        "bulk": "bulk_set_task_mode"},
        "set_deadlines":        {"single": "set_deadline",         "bulk": "bulk_set_deadlines"},
        "assign_resources":     {"single": "assign_resource",      "bulk": "bulk_assign_resources"},
    },
    "tool_categories": {
        "project_management": [
            "open_project", "new_project", "save_project", "save_project_as",
            "close_project", "get_project_info", "set_project_properties",
            "list_projects", "switch_project",
        ],
        "read_tasks": [
            "get_tasks", "get_task", "get_critical_path", "get_critical_path_sequence",
            "get_tasks_by_rag", "get_overdue_tasks", "get_tasks_by_resource",
            "filter_tasks", "group_tasks_by", "get_wbs_structure", "search_tasks",
            "get_progress_summary", "get_progress_by_wbs", "get_constraints",
            "get_task_dependencies", "get_dependency_chain",
            "get_critical_tasks_for_period", "find_available_slack",
        ],
        "write_tasks": [
            "add_task", "bulk_add_tasks", "add_recurring_task",
            "update_task", "bulk_update_tasks", "bulk_update_rag",
            "delete_task", "move_task", "indent_task", "copy_task_structure",
            "set_task_active",
            "set_task_mode", "bulk_set_task_mode",
            "set_constraint",
            "set_deadline", "bulk_set_deadlines",
            "clear_estimated_flags", "set_task_hyperlink",
            "set_task_calendar",
        ],
        "dependencies": [
            "add_predecessor", "bulk_add_predecessors",
            "remove_predecessor",
            "get_task_dependencies", "get_dependency_chain",
            "cross_project_link",
        ],
        "resources": [
            "get_resources", "add_resource", "update_resource", "delete_resource",
            "assign_resource", "bulk_assign_resources", "remove_resource_assignment",
            "get_resource_workload", "get_resource_availability",
            "get_resource_rate_tables", "set_resource_rate_table",
            "level_resources", "set_resource_calendar",
        ],
        "calendars": [
            "get_calendars", "create_calendar", "delete_calendar",
            "set_project_calendar", "set_working_hours",
            "set_calendar_exception", "delete_calendar_exception",
            "list_calendar_exceptions",
        ],
        "custom_fields": [
            "update_custom_fields",
            "get_custom_field_values", "rename_custom_fields",
        ],
        "schedule_analysis": [
            "get_schedule_analysis", "validate_schedule",
            "get_milestone_report", "what_if_delay",
            "calculate_project",
        ],
        "baselines_costs": [
            "save_baseline", "clear_baseline", "compare_baselines",
            "get_earned_value", "get_cost_summary", "get_actual_work",
            "get_variance_report", "get_timephased_data",
        ],
        "io_export": [
            "import_xml", "export_xml", "export_csv",
            "snapshot_to_json", "snapshot_diff", "insert_subproject",
        ],
        "safety_preview": [
            "dry_run_bulk_update", "undo_last",
            "update_project", "reschedule_incomplete_work",
        ],
        "display_filters": [
            "apply_filter",
        ],
        "hardening": [
            "session_info", "session_attach", "session_detach",
            "get_project_identity", "validate_project",
            "switch_project_confirmed", "list_open_projects",
            "set_calculation_mode", "get_calculation_mode", "calculate_now",
            "resolve_task", "resolve_resource", "store_stats", "invalidate_store",
            "get_ui_mode", "set_ui_mode", "get_ui_state",
            "bulk_update", "bulk_status",
        ],
        "mpxj_fast_read": [
            "mpxj_read_tasks", "mpxj_read_resources",
            "mpxj_read_project_info", "mpxj_read_assignments",
            "mpxj_read_calendars",
        ],
        "server_meta": [
            "health_check", "get_tool_guide",
        ],
    },
}


def register_tool_guide(mcp):
    """Register the get_tool_guide meta-tool on the FastMCP server."""

    @mcp.tool()
    def get_tool_guide() -> str:
        """Routing guide: which tool to call for common PM operations, and when to use bulk tools.

        Call this before starting any multi-step operation to avoid inefficient
        single-item loops. Returns categorized tool inventory organized by
        concern, efficiency rules, and single-to-bulk
        tool pairs.
        """
        return json.dumps(_TOOL_GUIDE, indent=2)

    logger.info("Registered get_tool_guide meta-tool.")
