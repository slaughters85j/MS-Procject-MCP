"""
Sprint 3, Item #12: ToolAnnotations on All Tools

Classifies every tool with MCP ToolAnnotations(title, readOnlyHint,
destructiveHint, idempotentHint) per the MCP spec. Applied post-registration
by matching tool names.

Classifies every tool with readOnlyHint, destructiveHint, idempotentHint.
WP-specific: bulk_update is idempotent (set-based); dry_run is read-only.
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

__all__ = ["apply_annotations", "TOOL_ANNOTATIONS"]


# ---------------------------------------------------------------------------
# Annotation specs: {tool_name: {title, readOnlyHint, destructiveHint, idempotentHint}}
#
# Every tool registered on our mcp instance must appear here. Missing tools
# get logged as warnings at startup — not silently skipped.
# ---------------------------------------------------------------------------

TOOL_ANNOTATIONS: Dict[str, Dict[str, Optional[bool]]] = {
    # --- Project management ---
    "open_project":          {"title": "Open Project",           "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "new_project":           {"title": "New Project",            "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    "get_project_info":      {"title": "Get Project Info",       "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "set_project_properties":{"title": "Set Project Properties", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "save_project":          {"title": "Save Project",           "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "save_project_as":       {"title": "Save Project As",        "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "close_project":         {"title": "Close Project",          "readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False},
    "list_projects":         {"title": "List Projects",          "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "switch_project":        {"title": "Switch Project",         "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},

    # --- Read tasks ---
    "get_tasks":             {"title": "Get Tasks",              "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_task":              {"title": "Get Task",               "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_critical_path":     {"title": "Get Critical Path",      "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_tasks_by_rag":      {"title": "Get Tasks by RAG",       "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_overdue_tasks":     {"title": "Get Overdue Tasks",      "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_tasks_by_resource": {"title": "Get Tasks by Resource",  "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "search_tasks":          {"title": "Search Tasks",           "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "filter_tasks":          {"title": "Filter Tasks",           "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "group_tasks_by":        {"title": "Group Tasks By",         "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_progress_summary":  {"title": "Get Progress Summary",   "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_wbs_structure":     {"title": "Get WBS Structure",      "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_task_dependencies":  {"title": "Get Task Dependencies",  "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_dependency_chain":  {"title": "Get Dependency Chain",   "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_constraints":       {"title": "Get Constraints",        "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_progress_by_wbs":   {"title": "Get Progress by WBS",    "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "find_available_slack":  {"title": "Find Available Slack",   "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_critical_path_sequence": {"title": "Get Critical Path Sequence", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
    "get_critical_tasks_for_period": {"title": "Get Critical Tasks for Period", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},

    # --- Write tasks ---
    "update_task":           {"title": "Update Task",            "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "add_task":              {"title": "Add Task",               "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    "delete_task":           {"title": "Delete Task",            "readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False},
    "move_task":             {"title": "Move Task",              "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "indent_task":           {"title": "Indent Task",            "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    "set_task_mode":         {"title": "Set Task Mode",          "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "set_constraint":        {"title": "Set Constraint",         "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "set_deadline":          {"title": "Set Deadline",           "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "set_task_active":       {"title": "Set Task Active",        "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "set_task_hyperlink":    {"title": "Set Task Hyperlink",     "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "set_task_calendar":     {"title": "Set Task Calendar",      "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "clear_estimated_flags": {"title": "Clear Estimated Flags",  "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "copy_task_structure":   {"title": "Copy Task Structure",    "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    "add_recurring_task":    {"title": "Add Recurring Task",     "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},

    # --- Bulk operations (WP-7: idempotent by design) ---
    "bulk_update_tasks":     {"title": "Bulk Update Tasks",      "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "bulk_add_tasks":        {"title": "Bulk Add Tasks",         "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    "bulk_update_rag":       {"title": "Bulk Update RAG",        "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "bulk_add_predecessors": {"title": "Bulk Add Predecessors",  "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    "bulk_set_task_mode":    {"title": "Bulk Set Task Mode",     "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "bulk_set_deadlines":    {"title": "Bulk Set Deadlines",     "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "bulk_assign_resources": {"title": "Bulk Assign Resources",  "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    "rename_custom_fields":  {"title": "Rename Custom Fields",   "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},

    # --- Dependencies ---
    "add_predecessor":       {"title": "Add Predecessor",        "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    "remove_predecessor":    {"title": "Remove Predecessor",     "readOnlyHint": False, "destructiveHint": True,  "idempotentHint": True},
    "cross_project_link":    {"title": "Cross Project Link",     "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},

    # --- Resources ---
    "get_resources":           {"title": "Get Resources",           "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "add_resource":            {"title": "Add Resource",            "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    "update_resource":         {"title": "Update Resource",         "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "delete_resource":         {"title": "Delete Resource",         "readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False},
    "assign_resource":         {"title": "Assign Resource",         "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    "remove_resource_assignment": {"title": "Remove Resource Assignment", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": True},
    "get_resource_workload":   {"title": "Get Resource Workload",   "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_resource_availability": {"title": "Get Resource Availability", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
    "get_resource_rate_tables": {"title": "Get Resource Rate Tables", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
    "set_resource_rate_table": {"title": "Set Resource Rate Table", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "level_resources":         {"title": "Level Resources",         "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "set_resource_calendar":   {"title": "Set Resource Calendar",   "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},

    # --- Calendars ---
    "get_calendars":           {"title": "Get Calendars",           "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "create_calendar":         {"title": "Create Calendar",         "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    "delete_calendar":         {"title": "Delete Calendar",         "readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False},
    "set_project_calendar":    {"title": "Set Project Calendar",    "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "set_working_hours":       {"title": "Set Working Hours",       "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "set_calendar_exception":  {"title": "Set Calendar Exception",  "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "delete_calendar_exception": {"title": "Delete Calendar Exception", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": False},
    "list_calendar_exceptions": {"title": "List Calendar Exceptions", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},

    # --- Custom fields ---
    "update_custom_fields":    {"title": "Update Custom Fields",    "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "get_custom_field_values": {"title": "Get Custom Field Values", "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},

    # --- Schedule analysis ---
    "get_schedule_analysis":   {"title": "Get Schedule Analysis",   "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "validate_schedule":       {"title": "Validate Schedule",       "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_milestone_report":    {"title": "Get Milestone Report",    "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "what_if_delay":           {"title": "What-If Delay",           "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "calculate_project":       {"title": "Calculate Project",       "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},

    # --- Baselines & costs ---
    "save_baseline":           {"title": "Save Baseline",           "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "clear_baseline":          {"title": "Clear Baseline",          "readOnlyHint": False, "destructiveHint": True,  "idempotentHint": True},
    "compare_baselines":       {"title": "Compare Baselines",       "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_earned_value":        {"title": "Get Earned Value",        "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_cost_summary":        {"title": "Get Cost Summary",        "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_actual_work":         {"title": "Get Actual Work",         "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_variance_report":     {"title": "Get Variance Report",     "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_timephased_data":     {"title": "Get Timephased Data",     "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},

    # --- IO / Export ---
    "import_xml":              {"title": "Import XML",              "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "export_xml":              {"title": "Export XML",              "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "export_csv":              {"title": "Export CSV",              "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "snapshot_to_json":        {"title": "Snapshot to JSON",        "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "snapshot_diff":           {"title": "Snapshot Diff",           "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "insert_subproject":       {"title": "Insert Subproject",       "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},

    # --- Safety / preview ---
    "dry_run_bulk_update":     {"title": "Dry Run Bulk Update",     "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "undo_last":               {"title": "Undo Last",               "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    "update_project":          {"title": "Update Project",          "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "reschedule_incomplete_work": {"title": "Reschedule Incomplete Work", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "apply_filter":            {"title": "Apply Filter",            "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},

    # --- Server meta ---
    "health_check":            {"title": "Health Check",            "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "get_tool_guide":          {"title": "Get Tool Guide",          "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},

    # --- WP-1: Session tools ---
    "session_attach":          {"title": "Session Attach",          "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "session_detach":          {"title": "Session Detach",          "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "session_info":            {"title": "Session Info",            "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},

    # --- WP-2: Identity tools ---
    "get_project_identity":    {"title": "Get Project Identity",    "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "validate_project":        {"title": "Validate Project",        "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "switch_project_confirmed": {"title": "Switch Project Confirmed", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "list_open_projects":      {"title": "List Open Projects",      "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},

    # --- WP-4: Calc tools ---
    "get_calculation_mode":    {"title": "Get Calculation Mode",    "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "set_calculation_mode":    {"title": "Set Calculation Mode",    "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "calculate_now":           {"title": "Calculate Now",           "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},

    # --- WP-5: Store tools ---
    "resolve_task":            {"title": "Resolve Task",            "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "resolve_resource":        {"title": "Resolve Resource",        "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "invalidate_store":        {"title": "Invalidate Store",        "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "store_stats":             {"title": "Store Stats",             "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},

    # --- WP-6: UI tools ---
    "get_ui_mode":             {"title": "Get UI Mode",             "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "set_ui_mode":             {"title": "Set UI Mode",             "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "get_ui_state":            {"title": "Get UI State",            "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},

    # --- WP-7: Bulk ops (registered via bulk_tools.py) ---
    "bulk_update":             {"title": "Bulk Update",             "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "bulk_status":             {"title": "Bulk Status",             "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},

    # --- Sprint 4: mpxj fast-read (reads SAVED .mpp file, no COM) ---
    "mpxj_read_tasks":         {"title": "MPXJ Read Tasks",         "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "mpxj_read_resources":     {"title": "MPXJ Read Resources",     "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "mpxj_read_project_info":  {"title": "MPXJ Read Project Info",  "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "mpxj_read_assignments":   {"title": "MPXJ Read Assignments",   "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
    "mpxj_read_calendars":     {"title": "MPXJ Read Calendars",     "readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True},
}


# ---------------------------------------------------------------------------
# apply_annotations — post-registration pass
# ---------------------------------------------------------------------------

def apply_annotations(server) -> int:
    """Apply ToolAnnotations to every tool registered on the FastMCP server.

    Reaches into FastMCP's tool manager to set the annotations attribute on
    each tool. Written to fail into a no-op: an mcp release that changes the
    internals leaves the tools functional but unannotated.

    Returns the number of tools annotated.
    """
    try:
        from mcp.types import ToolAnnotations
    except ImportError:
        logger.warning(
            "mcp.types.ToolAnnotations not available — "
            "annotations require mcp>=1.20. Skipping."
        )
        return 0

    try:
        tools = server._tool_manager._tools
    except Exception:
        logger.warning("Could not access FastMCP tool manager — skipping annotations.")
        return 0

    annotated = 0
    registered_names = set(tools.keys())
    classified_names = set(TOOL_ANNOTATIONS.keys())

    # Warn about tools we haven't classified
    unclassified = registered_names - classified_names
    if unclassified:
        logger.warning(
            "Tools without ToolAnnotations classification: %s",
            sorted(unclassified),
        )

    for name, spec in TOOL_ANNOTATIONS.items():
        if name not in tools:
            continue
        try:
            tool = tools[name]
            tool.annotations = ToolAnnotations(
                title=spec.get("title"),
                readOnlyHint=spec.get("readOnlyHint"),
                destructiveHint=spec.get("destructiveHint"),
                idempotentHint=spec.get("idempotentHint"),
            )
            annotated += 1
        except Exception as exc:
            logger.debug("Failed to annotate tool %s: %s", name, exc)

    logger.info(
        "ToolAnnotations applied to %d/%d tools (%d unclassified).",
        annotated, len(registered_names), len(unclassified),
    )
    return annotated
