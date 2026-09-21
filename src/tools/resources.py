"""
Resource pool and assignment management.
"""

import json

from ..com_helpers import get_app, get_proj, _find_task
from ..guards import (
    is_dry_run, dry_run_response, prepare_resource_response, DEFAULT_PAGE_LIMIT, _RESPONSE_MGMT,
)


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
        Add a resource to the project resource pool.

        Args:
            name:          Resource name (required).
            type:          0=Work (default), 1=Material, 2=Cost.
            max_units:     Maximum allocation units (default 1.0 = 100%).
            standard_rate: Standard rate as string (e.g. "50/h", "100/d").
            cost_per_use:  Fixed cost per use (default 0).
        """
        app  = get_app()
        proj = get_proj(app)

        r = proj.Resources.Add(name)
        r.Type = type
        if type == 0:  # MaxUnits only valid for Work resources
            r.MaxUnits = max_units
        if standard_rate:
            r.StandardRate = standard_rate
        if cost_per_use > 0:
            r.CostPerUse = cost_per_use

        app.FileSave()
        return json.dumps({
            "status":    "created",
            "unique_id": r.UniqueID,
            "id":        r.ID,
            "name":      r.Name,
            "type":      r.Type,
            "max_units": r.MaxUnits,
        }, indent=2)


    @mcp.tool()
    def assign_resource(task_unique_id: int, resource_name: str, units: float = 1.0) -> str:
        """
        Assign a resource to a task. If the resource doesn't exist, it is created.
        If the task already has resources, the new one is appended.

        Args:
            task_unique_id: Task UniqueID (required).
            resource_name:  Resource name to assign (required).
            units:          Allocation units, e.g. 1.0 = 100% (default 1.0).
        """
        app  = get_app()
        proj = get_proj(app)

        # Find task
        task = None
        for t in proj.Tasks:
            if t is not None and t.UniqueID == task_unique_id:
                task = t
                break
        if task is None:
            return json.dumps({"error": f"Task UniqueID {task_unique_id} not found."})

        # Check if resource exists, create if not
        res_exists = False
        for r in proj.Resources:
            if r is not None and r.Name.lower() == resource_name.lower():
                res_exists = True
                break
        if not res_exists:
            proj.Resources.Add(resource_name)

        # Append to ResourceNames (handles existing assignments)
        existing = (task.ResourceNames or "").strip()
        if existing:
            # Check if already assigned
            existing_names = [n.strip().lower() for n in existing.split(",")]
            if resource_name.lower() not in existing_names:
                task.ResourceNames = existing + "," + resource_name
        else:
            task.ResourceNames = resource_name

        app.FileSave()
        return json.dumps({
            "status":         "assigned",
            "task_unique_id": task_unique_id,
            "task_name":      task.Name,
            "resource_name":  resource_name,
            "resource_names": task.ResourceNames,
        }, indent=2)


    @mcp.tool()
    def bulk_assign_resources(assignments_json: str) -> str:
        """
        Assign resources to multiple tasks in one call.

        Args:
            assignments_json: JSON string — list of {task_unique_id, resource_name, units (optional)}.
                Example: '[{"task_unique_id": 42, "resource_name": "Alice"},
                           {"task_unique_id": 55, "resource_name": "Bob", "units": 0.5}]'
        """
        items = json.loads(assignments_json)
        app   = get_app()
        proj  = get_proj(app)

        app.Calculation = 0
        try:
            uid_map = {t.UniqueID: t for t in proj.Tasks if t is not None}
            # Get existing resource names
            existing_resources = set()
            for r in proj.Resources:
                if r is not None:
                    existing_resources.add(r.Name.lower())

            assigned = 0
            errors = []
            created_resources = []

            for item in items:
                task_uid = item["task_unique_id"]
                res_name = item["resource_name"]

                t = uid_map.get(task_uid)
                if t is None:
                    errors.append({"task_unique_id": task_uid, "error": "task not found"})
                    continue

                # Create resource if needed
                if res_name.lower() not in existing_resources:
                    proj.Resources.Add(res_name)
                    existing_resources.add(res_name.lower())
                    created_resources.append(res_name)

                # Append to ResourceNames
                existing = (t.ResourceNames or "").strip()
                if existing:
                    existing_names = [n.strip().lower() for n in existing.split(",")]
                    if res_name.lower() not in existing_names:
                        t.ResourceNames = existing + "," + res_name
                else:
                    t.ResourceNames = res_name

                assigned += 1
        finally:
            app.CalculateProject()
            app.Calculation = -1

        return json.dumps({
            "assigned":          assigned,
            "errors":            errors,
            "created_resources": created_resources,
        }, indent=2)


    @mcp.tool()
    def remove_resource_assignment(task_unique_id: int, resource_name: str) -> str:
        """
        Remove a specific resource from a task.

        Args:
            task_unique_id: Task UniqueID (required).
            resource_name:  Resource name to remove (required).
        """
        app  = get_app()
        proj = get_proj(app)

        t = _find_task(proj, task_unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {task_unique_id} not found."})

        existing = (t.ResourceNames or "").strip()
        if not existing:
            return json.dumps({"error": f"Task '{t.Name}' has no resources assigned."})

        names = [n.strip() for n in existing.split(",")]
        filtered = [n for n in names if n.lower() != resource_name.lower()]

        if len(filtered) == len(names):
            return json.dumps({"error": f"Resource '{resource_name}' not assigned to task '{t.Name}'. Current: {existing}"})

        t.ResourceNames = ",".join(filtered) if filtered else ""

        return json.dumps({
            "status":           "removed",
            "task_name":        t.Name,
            "removed":          resource_name,
            "resource_names_now": t.ResourceNames,
        }, indent=2)


    @mcp.tool()
    def update_resource(resource_name: str, new_name: str = "", max_units: float = -1, standard_rate: str = "", cost_per_use: float = -1) -> str:
        """
        Modify an existing resource's properties.

        Args:
            resource_name: Current resource name (required, case-insensitive).
            new_name:      New name for the resource (optional).
            max_units:     Maximum allocation units, e.g. 2.0 = 200% (optional, -1 = no change).
            standard_rate: Standard rate as string, e.g. '50/h' (optional).
            cost_per_use:  Fixed cost per use (optional, -1 = no change).
        """
        app  = get_app()
        proj = get_proj(app)

        resource = None
        for r in proj.Resources:
            if r is not None and r.Name.lower() == resource_name.lower():
                resource = r
                break

        if resource is None:
            avail = [r.Name for r in proj.Resources if r is not None]
            return json.dumps({"error": f"Resource '{resource_name}' not found. Available: {avail}"})

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

        return json.dumps({
            "status":  "updated",
            "name":    resource.Name,
            "changed": changed,
        }, indent=2)


    @mcp.tool()
    def delete_resource(resource_name: str) -> str:
        """
        Delete a resource from the project pool (case-insensitive match).
        All task assignments referencing this resource are cleared first.
        """
        if is_dry_run():
            return dry_run_response("delete_resource", {"resource_name": resource_name})
        app  = get_app()
        proj = get_proj(app)

        target = None
        for r in proj.Resources:
            if r is not None and r.Name.lower() == resource_name.lower():
                target = r
                break

        if target is None:
            return json.dumps({"error": f"Resource '{resource_name}' not found."})

        # Clear assignments first
        assignments_cleared = 0
        # Iterate in reverse to avoid index shifting
        for i in range(target.Assignments.Count, 0, -1):
            try:
                target.Assignments(i).Delete()
                assignments_cleared += 1
            except Exception:
                pass

        name = target.Name
        try:
            target.Delete()
        except Exception as e:
            return json.dumps({"error": f"Failed to delete resource: {e}"})

        app.FileSave()
        return json.dumps({
            "status":              "deleted",
            "name":                name,
            "assignments_cleared": assignments_cleared,
        }, indent=2)
