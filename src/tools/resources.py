"""
Resource pool and assignment management.
"""

import json

from ..com_helpers import get_app, get_proj, _find_task
from ..com_write import commit, batch_calc, resolve_resource as _resource
from ..guards import (
    prepare_resource_response, DEFAULT_PAGE_LIMIT, _RESPONSE_MGMT,
)

_FORBIDDEN_NAME_CHARS = "[],;"


def _check_new_name(proj, name):
    """A resource name must be non-empty, free of [ ] and list separators, and unique."""
    if not name or not name.strip():
        raise ValueError("Resource name is required.")
    bad = [c for c in _FORBIDDEN_NAME_CHARS if c in name]
    if bad:
        raise ValueError(f"Resource names cannot contain {bad} (brackets or list separators).")
    if any(r is not None and r.Name.lower() == name.lower() for r in proj.Resources):
        raise ValueError(f"A resource named '{name}' already exists.")


def _assign(task, resource, units):
    """Add one assignment through Task.Assignments. Raises ValueError on invalid units or duplicates."""
    if units <= 0:
        raise ValueError("units must be greater than 0.")
    if any(a.ResourceUniqueID == resource.UniqueID for a in task.Assignments):
        raise ValueError(f"'{resource.Name}' is already assigned to '{task.Name}'.")
    task.Assignments.Add(task.ID, resource.ID, units)


def register_resources_tools(mcp):
    """Register the resources tools on the FastMCP instance."""

    @mcp.tool()
    def get_resources(
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> str:
        """Get all resources in the active project.

        Args:
            offset: Pagination offset (default 0).
            limit:  Page size (default 200, -1 for all).
        """
        app  = get_app()
        proj = get_proj(app)

        results = []
        for r in proj.Resources:
            if r is not None:
                results.append({
                    "unique_id":  r.UniqueID,
                    "id":         r.ID,
                    "name":       r.Name,
                    "initials":   r.Initials,
                    "type":       r.Type,
                    "max_units":  r.MaxUnits,
                    "cost":       r.StandardRate,
                    "task_count": r.Assignments.Count,
                })

        if _RESPONSE_MGMT:
            return prepare_resource_response(results, offset=offset, limit=limit)
        # Fallback: still respect offset/limit even without response module
        total = len(results)
        if offset > 0:
            results = results[offset:]
        if limit > 0:
            results = results[:limit]
        return json.dumps({"count": total, "resources": results}, indent=2)


    @mcp.tool()
    def add_resource(
        name:          str,
        type:          int   = 0,
        max_units:     float = 1.0,
        standard_rate: str   = "",
        cost_per_use:  float = 0.0,
    ) -> str:
        """
        Add a resource to the project resource pool. The name must be unique.

        Args:
            name:          Resource name (required, unique, no [ ] or list separators).
            type:          0=Work (default), 1=Material, 2=Cost.
            max_units:     Maximum allocation units for Work resources (default 1.0 = 100%).
            standard_rate: Standard rate as string (e.g. "50/h", "100/d").
            cost_per_use:  Fixed cost per use (default 0).
        """
        app  = get_app()
        proj = get_proj(app)
        _check_new_name(proj, name)
        if type not in (0, 1, 2):
            raise ValueError("type must be 0 (Work), 1 (Material) or 2 (Cost).")
        if type == 0 and max_units <= 0:
            raise ValueError("max_units must be greater than 0.")
        r = proj.Resources.Add(name)
        try:
            r.Type = type
            if type == 0:  # MaxUnits only valid for Work resources
                r.MaxUnits = max_units
            if standard_rate:
                r.StandardRate = standard_rate
            if cost_per_use > 0:
                r.CostPerUse = cost_per_use
        except Exception:
            r.Delete()  # never leave a half-configured resource behind
            raise
        commit(app, proj)
        return json.dumps({"status": "created", "unique_id": r.UniqueID, "id": r.ID, "name": r.Name,
                           "type": r.Type, "max_units": r.MaxUnits}, indent=2)

    @mcp.tool()
    def assign_resource(task_unique_id: int, resource_name: str, units: float = 1.0) -> str:
        """
        Assign an existing resource to a task (resources are never created implicitly;
        use add_resource first).

        Args:
            task_unique_id: Task UniqueID (required).
            resource_name:  Name of an existing resource (required).
            units:          Allocation units, e.g. 1.0 = 100%, 0.5 = 50% (default 1.0).
        """
        app  = get_app()
        proj = get_proj(app)
        task = _find_task(proj, task_unique_id)
        if task is None:
            return json.dumps({"error": f"Task UniqueID {task_unique_id} not found."})
        _assign(task, _resource(proj, resource_name), units)
        commit(app, proj)
        return json.dumps({"status": "assigned", "task_unique_id": task_unique_id, "task_name": task.Name,
                           "resource_name": resource_name, "units": units,
                           "resource_names": task.ResourceNames}, indent=2)

    @mcp.tool()
    def bulk_assign_resources(assignments_json: str) -> str:
        """
        Assign existing resources to multiple tasks in one call. Each item is validated and
        applied independently; failures are reported per item.

        Args:
            assignments_json: JSON string — list of {task_unique_id, resource_name, units (optional)}.
                Example: '[{"task_unique_id": 42, "resource_name": "Alice"},
                           {"task_unique_id": 55, "resource_name": "Bob", "units": 0.5}]'
        """
        from ..tool_guardrails import _describe_exception
        items = json.loads(assignments_json)
        if not isinstance(items, list):
            raise ValueError("assignments_json must be a JSON array of objects.")
        app  = get_app()
        proj = get_proj(app)
        assigned, errors = 0, []
        with batch_calc(app):
            for i, item in enumerate(items):
                try:
                    task = _find_task(proj, item.get("task_unique_id"))
                    if task is None:
                        raise ValueError(f"Task UniqueID {item.get('task_unique_id')} not found.")
                    _assign(task, _resource(proj, item.get("resource_name") or ""), float(item.get("units", 1.0)))
                    assigned += 1
                except Exception as e:
                    errors.append({"index": i, "item": item, "error": _describe_exception(e)[0]})
        commit(app, proj)
        return json.dumps({"assigned": assigned, "errors": errors}, indent=2)

    @mcp.tool()
    def remove_resource_assignment(task_unique_id: int, resource_name: str) -> str:
        """
        Remove a specific resource from a task (works whatever its units, e.g. 'Bob[50%]').

        Args:
            task_unique_id: Task UniqueID (required).
            resource_name:  Resource name to remove (required).
        """
        app  = get_app()
        proj = get_proj(app)
        t = _find_task(proj, task_unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {task_unique_id} not found."})
        match = next((a for a in t.Assignments if a.ResourceName.lower() == resource_name.lower()), None)
        if match is None:
            return json.dumps({"error": f"Resource '{resource_name}' not assigned to task '{t.Name}'. "
                                        f"Current: {t.ResourceNames or '(none)'}"})
        match.Delete()
        commit(app, proj)
        return json.dumps({"status": "removed", "task_name": t.Name, "removed": resource_name,
                           "resource_names_now": t.ResourceNames}, indent=2)

    @mcp.tool()
    def update_resource(resource_name: str, new_name: str = "", max_units: float = -1,
                        standard_rate: str = "", cost_per_use: float = -1) -> str:
        """
        Modify an existing resource's properties.

        Args:
            resource_name: Current resource name (required, case-insensitive).
            new_name:      New name (optional; must not collide with another resource).
            max_units:     Maximum allocation units, e.g. 2.0 = 200% (optional, -1 = no change).
            standard_rate: Standard rate as string, e.g. '50/h' (optional).
            cost_per_use:  Fixed cost per use (optional, -1 = no change).
        """
        app  = get_app()
        proj = get_proj(app)
        resource = _resource(proj, resource_name)
        if new_name and new_name.lower() != resource.Name.lower():
            _check_new_name(proj, new_name)
        changed = []
        if new_name:
            resource.Name = new_name
            changed.append("name")
        if max_units >= 0:
            resource.MaxUnits = max_units
            changed.append("max_units")
        if standard_rate:
            resource.StandardRate = standard_rate
            changed.append("standard_rate")
        if cost_per_use >= 0:
            resource.CostPerUse = cost_per_use
            changed.append("cost_per_use")
        if not changed:
            return json.dumps({"error": "No changes were provided."})
        commit(app, proj)
        return json.dumps({"status": "updated", "name": resource.Name, "changed": changed}, indent=2)

    @mcp.tool()
    def delete_resource(resource_name: str) -> str:
        """
        Delete a resource from the project pool (case-insensitive match).
        All task assignments referencing this resource are removed with it.
        """
        app  = get_app()
        proj = get_proj(app)
        target = _resource(proj, resource_name)
        name, cleared = target.Name, target.Assignments.Count
        target.Delete()
        commit(app, proj)
        return json.dumps({"status": "deleted", "name": name, "assignments_cleared": cleared}, indent=2)
