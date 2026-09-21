"""
WP-2: Project identity MCP tools.

Exposes project identity and switch_project as explicit MCP tools.
These replace implicit "whatever is active" behavior.

NOTE: Testing against live MS Project remains required.
"""

import json
import logging
from dataclasses import asdict

from .project_identity import (
    get_active_identity,
    validate_project_target,
    ProjectIdentity,
    ProjectMismatchError,
)
from .project_session import get_session

logger = logging.getLogger(__name__)


def register_identity_tools(mcp):
    """Register project identity tools on the given FastMCP instance."""

    @mcp.tool()
    def get_project_identity() -> dict:
        """
        Get the identity of the currently active project.

        Returns the canonical path, short hash ID, and display name.
        Use the hash_id or canonical path as project_id in mutating tools.
        """
        session = get_session()
        identity = get_active_identity(session.app)
        if identity is None:
            return {"error": "No project is currently open."}
        return asdict(identity)

    @mcp.tool()
    def validate_project(project_id: str) -> dict:
        """
        Validate that project_id matches the active project.

        Use this to confirm you're targeting the right project before
        a batch of operations.

        Args:
            project_id: File path or hash_id of the target project.
        """
        session = get_session()
        try:
            identity = validate_project_target(session.app, project_id)
            return {"valid": True, **asdict(identity)}
        except ProjectMismatchError as e:
            return {
                "valid": False,
                "error": str(e),
                "requested": e.requested,
                "active": e.active,
            }
        except RuntimeError as e:
            return {"valid": False, "error": str(e)}

    # Registered under its own name: the legacy server.py switch_project keeps its
    # name and signature, and FastMCP skips a second tool with the same name.
    @mcp.tool(name="switch_project_confirmed")
    def switch_project(project_name_or_index: str, confirm: bool = False) -> dict:
        """
        Explicitly switch the active project in MS Project.

        This is a DELIBERATE operation — never a side effect of another tool.
        Requires confirm=True to actually execute the switch. Matches the exact
        project name or 1-based index (the legacy switch_project tool switches
        immediately and matches a name substring).

        Args:
            project_name_or_index: Project name or 1-based index.
            confirm: Must be True to execute. False returns a preview.
        """
        session = get_session()
        app = session.app

        try:
            projects_count = app.Projects.Count
            if projects_count == 0:
                return {"error": "No projects are open."}

            # Resolve the target project
            target_proj = None
            try:
                idx = int(project_name_or_index)
                if 1 <= idx <= projects_count:
                    target_proj = app.Projects(idx)
            except (ValueError, TypeError):
                # Try by name
                for i in range(1, projects_count + 1):
                    p = app.Projects(i)
                    if p.Name == project_name_or_index:
                        target_proj = p
                        break

            if target_proj is None:
                return {
                    "error": f"Project '{project_name_or_index}' not found.",
                    "available": [
                        app.Projects(i).Name
                        for i in range(1, projects_count + 1)
                    ],
                }

            current = get_active_identity(app)
            target_identity = ProjectIdentity.from_path(target_proj.FullName)

            if current and current.canonical == target_identity.canonical:
                return {
                    "status": "already_active",
                    **asdict(target_identity),
                }

            if not confirm:
                return {
                    "status": "preview",
                    "message": (
                        f"Will switch from '{current.display_name if current else 'none'}' "
                        f"to '{target_identity.display_name}'. "
                        "Set confirm=True to execute."
                    ),
                    "current": asdict(current) if current else None,
                    "target": asdict(target_identity),
                }

            # Execute the switch
            app.Projects(target_proj.Name).Activate()
            new_identity = get_active_identity(app)

            return {
                "status": "switched",
                "previous": asdict(current) if current else None,
                "active": asdict(new_identity) if new_identity else None,
            }

        except Exception as e:
            return {"error": f"Switch failed: {e}"}

    @mcp.tool()
    def list_open_projects() -> dict:
        """
        List all currently open projects with their identities.

        Returns each project's name, canonical path, and hash_id.
        """
        session = get_session()
        app = session.app

        try:
            count = app.Projects.Count
            if count == 0:
                return {"projects": [], "count": 0}

            projects = []
            active_path = None
            try:
                active_path = app.ActiveProject.FullName
            except Exception:
                pass

            for i in range(1, count + 1):
                proj = app.Projects(i)
                identity = ProjectIdentity.from_path(proj.FullName)
                projects.append({
                    **asdict(identity),
                    "index": i,
                    "name": proj.Name,
                    "is_active": (
                        identity.canonical == ProjectIdentity.from_path(active_path).canonical
                        if active_path else False
                    ),
                })

            return {"projects": projects, "count": count}

        except Exception as e:
            return {"error": f"Failed to list projects: {e}"}
