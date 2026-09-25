"""
Read-only task lookups: paged task lists, single tasks, RAG, overdue, per-resource, and keyword search.
"""

import json

from ..com_helpers import get_app, get_proj, task_to_dict, _to_naive, is_overdue, assigned_resource_names
from ..com_write import validate_rag
from ..guards import prepare_task_response, DEFAULT_PAGE_LIMIT, _RESPONSE_MGMT


def register_task_query_tools(mcp):
    """Register the task query tools on the FastMCP instance."""

    @mcp.tool()
    def get_tasks(
        include_summary: bool = False,
        outline_level: int = 0,
        keyword: str = "",
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> str:
        """
        Get all tasks from the active project.

        Args:
            include_summary: Include summary/parent tasks (default False).
            outline_level:   Filter to a specific outline level (0 = all).
            keyword:         Filter tasks whose name contains this string (case-insensitive).
            offset:          Pagination offset (default 0).
            limit:           Page size (default 200, -1 for all).
        """
        app  = get_app()
        proj = get_proj(app)

        results = []
        for t in proj.Tasks:
            if t is None:
                continue
            if not include_summary and t.Summary:
                continue
            if outline_level > 0 and t.OutlineLevel != outline_level:
                continue
            if keyword and keyword.lower() not in t.Name.lower():
                continue
            results.append(task_to_dict(t, proj))

        if _RESPONSE_MGMT:
            return prepare_task_response(results, offset=offset, limit=limit)
        # Fallback: still respect offset/limit even without response module
        total = len(results)
        if offset > 0:
            results = results[offset:]
        if limit > 0:
            results = results[:limit]
        return json.dumps({"count": total, "tasks": results}, indent=2)


    @mcp.tool()
    def get_task(unique_id: int) -> str:
        """Get full details for a single task by its UniqueID."""
        app  = get_app()
        proj = get_proj(app)

        for t in proj.Tasks:
            if t is not None and t.UniqueID == unique_id:
                return json.dumps(task_to_dict(t, proj), indent=2)

        return json.dumps({"error": f"Task UniqueID {unique_id} not found."})


    @mcp.tool()
    def get_tasks_by_rag(rag: str = "Red") -> str:
        """
        Return tasks filtered by RAG status stored in the Text1 custom field.
        rag: 'Red', 'Amber', or 'Green'
        """
        rag  = validate_rag(rag)
        app  = get_app()
        proj = get_proj(app)

        results = []
        for t in proj.Tasks:
            if t is not None and not t.Summary:
                if (t.Text1 or "").strip().lower() == rag.lower():
                    results.append(task_to_dict(t, proj))

        return json.dumps({"rag": rag, "count": len(results), "tasks": results}, indent=2)


    @mcp.tool()
    def get_overdue_tasks() -> str:
        """
        Return overdue tasks: non-summary tasks (milestones included) below 100% complete
        whose Finish date is in the past. Same definition as get_progress_summary's overdue count.
        """
        import datetime
        now  = datetime.datetime.now()
        app  = get_app()
        proj = get_proj(app)
        results = [task_to_dict(t, proj) for t in proj.Tasks if t is not None and is_overdue(t, now)]
        return json.dumps({"count": len(results), "tasks": results}, indent=2)


    @mcp.tool()
    def get_tasks_by_resource(resource_name: str) -> str:
        """Return all tasks assigned to a named resource (case-insensitive exact name match)."""
        app  = get_app()
        proj = get_proj(app)

        results = []
        name_lower = resource_name.strip().lower()
        for t in proj.Tasks:
            if t is not None and not t.Summary:
                if name_lower in [n.lower() for n in assigned_resource_names(t)]:
                    results.append(task_to_dict(t, proj))

        return json.dumps({
            "resource": resource_name,
            "count":    len(results),
            "tasks":    results,
        }, indent=2)


    @mcp.tool()
    def search_tasks(
        query: str,
        include_summary: bool = False,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> str:
        """
        Search for tasks by name (case-insensitive substring match).
        Returns matching tasks with their UniqueIDs for use in other tools.

        Args:
            query:           Search string (case-insensitive substring match on task name).
            include_summary: Include summary/parent tasks (default False).
            offset:          Pagination offset (default 0).
            limit:           Page size (default 200, -1 for all).
        """
        return get_tasks(include_summary=include_summary, keyword=query,
                         offset=offset, limit=limit)
