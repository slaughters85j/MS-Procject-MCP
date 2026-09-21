"""
Sprint 4: FastMCP tools for mpxj fast-read path.

These tools read from the SAVED .mpp file on disk — NOT the live COM state.
Unsaved changes in MS Project are NOT reflected. For live state, use the
COM-based tools (get_tasks, get_resources, etc.).

All tools:
  - Apply MSPROJECT_SAFE_ROOT path confinement to file paths.
  - Apply response management (paginate, strip_empty, format_response).
  - Return a 'source' block indicating backend=mpxj and read timestamp.
  - Provide descriptive error messages for MCP-consuming agents.
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = ["register_mpxj_tools"]


def register_mpxj_tools(mcp) -> None:
    """Register all mpxj fast-read tools on the FastMCP server instance."""

    # Import dependencies with graceful fallback
    from .mpxj_reader import (
        read_tasks, read_resources, read_assignments,
        read_calendars, read_project_info,
        MpxjError, MpxjNotAvailableError, MpxjFileError, MpxjParseError,
        is_mpxj_available,
    )
    from .safe_path import validate_safe_path
    from .response import (
        paginate, strip_empty_list, format_response,
        DEFAULT_PAGE_LIMIT,
    )

    def _safe_resolve(file_path: str) -> str:
        """Validate file path through MSPROJECT_SAFE_ROOT confinement."""
        return validate_safe_path(file_path)

    def _error_response(error: Exception) -> str:
        """Format an MpxjError into a readable JSON error response."""
        error_type = type(error).__name__
        return format_response({
            "error": True,
            "error_type": error_type,
            "message": str(error),
        })

    # ------------------------------------------------------------------
    # mpxj_read_tasks
    # ------------------------------------------------------------------

    @mcp.tool()
    def mpxj_read_tasks(
        file_path: str,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
        strip: bool = True,
    ) -> str:
        """Read tasks from a SAVED .mpp file on disk (fast path, no COM needed).

        Reads the .mpp file directly using mpxj — works on Mac, Linux, and Windows
        without MS Project installed. 20-30x faster than COM on large schedules.

        IMPORTANT: Reads the SAVED file, NOT live COM state. Unsaved changes in
        MS Project are NOT reflected. For live state, use get_tasks instead.

        Args:
            file_path: Path to the .mpp file. Must be within MSPROJECT_SAFE_ROOT.
            offset: Pagination start index (0-based). Default 0.
            limit: Maximum tasks to return. Default 200. Use -1 for all.
            strip: Strip empty/zero fields to reduce response size. Default True.

        Returns:
            JSON with tasks array, pagination metadata, and source block.
        """
        try:
            resolved = _safe_resolve(file_path)
            tasks, source = read_tasks(resolved)

            page, pagination = paginate(tasks, offset=offset, limit=limit)
            if strip:
                page = strip_empty_list(page)

            return format_response({
                "tasks": page,
                "pagination": pagination,
                "source": source,
            })
        except (MpxjError, ValueError) as exc:
            return _error_response(exc)

    # ------------------------------------------------------------------
    # mpxj_read_resources
    # ------------------------------------------------------------------

    @mcp.tool()
    def mpxj_read_resources(
        file_path: str,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
        strip: bool = True,
    ) -> str:
        """Read resources from a SAVED .mpp file on disk (fast path, no COM needed).

        Reads the .mpp file directly using mpxj — works on Mac, Linux, and Windows
        without MS Project installed.

        IMPORTANT: Reads the SAVED file, NOT live COM state. Unsaved changes in
        MS Project are NOT reflected. For live state, use get_resources instead.

        Args:
            file_path: Path to the .mpp file. Must be within MSPROJECT_SAFE_ROOT.
            offset: Pagination start index (0-based). Default 0.
            limit: Maximum resources to return. Default 200. Use -1 for all.
            strip: Strip empty/zero fields to reduce response size. Default True.

        Returns:
            JSON with resources array, pagination metadata, and source block.
        """
        try:
            resolved = _safe_resolve(file_path)
            resources, source = read_resources(resolved)

            page, pagination = paginate(resources, offset=offset, limit=limit)
            if strip:
                page = strip_empty_list(page)

            return format_response({
                "resources": page,
                "pagination": pagination,
                "source": source,
            })
        except (MpxjError, ValueError) as exc:
            return _error_response(exc)

    # ------------------------------------------------------------------
    # mpxj_read_project_info
    # ------------------------------------------------------------------

    @mcp.tool()
    def mpxj_read_project_info(file_path: str) -> str:
        """Read project-level properties from a SAVED .mpp file on disk (fast path).

        Returns title, author, manager, dates, calendar settings, and summary
        counts (tasks, resources, assignments, calendars).

        IMPORTANT: Reads the SAVED file, NOT live COM state. Unsaved changes in
        MS Project are NOT reflected. For live state, use get_project_info instead.

        Args:
            file_path: Path to the .mpp file. Must be within MSPROJECT_SAFE_ROOT.

        Returns:
            JSON with project properties and source block.
        """
        try:
            resolved = _safe_resolve(file_path)
            info, source = read_project_info(resolved)

            return format_response({
                "project_info": info,
                "source": source,
            })
        except (MpxjError, ValueError) as exc:
            return _error_response(exc)

    # ------------------------------------------------------------------
    # mpxj_read_assignments
    # ------------------------------------------------------------------

    @mcp.tool()
    def mpxj_read_assignments(
        file_path: str,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
        strip: bool = True,
    ) -> str:
        """Read resource assignments from a SAVED .mpp file on disk (fast path).

        Returns all task-to-resource assignments with work, cost, and dates.

        IMPORTANT: Reads the SAVED file, NOT live COM state. Unsaved changes in
        MS Project are NOT reflected.

        Args:
            file_path: Path to the .mpp file. Must be within MSPROJECT_SAFE_ROOT.
            offset: Pagination start index (0-based). Default 0.
            limit: Maximum assignments to return. Default 200. Use -1 for all.
            strip: Strip empty/zero fields to reduce response size. Default True.

        Returns:
            JSON with assignments array, pagination metadata, and source block.
        """
        try:
            resolved = _safe_resolve(file_path)
            assignments, source = read_assignments(resolved)

            page, pagination = paginate(assignments, offset=offset, limit=limit)
            if strip:
                page = strip_empty_list(page)

            return format_response({
                "assignments": page,
                "pagination": pagination,
                "source": source,
            })
        except (MpxjError, ValueError) as exc:
            return _error_response(exc)

    # ------------------------------------------------------------------
    # mpxj_read_calendars
    # ------------------------------------------------------------------

    @mcp.tool()
    def mpxj_read_calendars(
        file_path: str,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
        strip: bool = True,
    ) -> str:
        """Read calendars from a SAVED .mpp file on disk (fast path).

        Returns all project calendars with working days, hours, and exceptions.

        IMPORTANT: Reads the SAVED file, NOT live COM state. Unsaved changes in
        MS Project are NOT reflected.

        Args:
            file_path: Path to the .mpp file. Must be within MSPROJECT_SAFE_ROOT.
            offset: Pagination start index (0-based). Default 0.
            limit: Maximum calendars to return. Default 200. Use -1 for all.
            strip: Strip empty/zero fields to reduce response size. Default True.

        Returns:
            JSON with calendars array, pagination metadata, and source block.
        """
        try:
            resolved = _safe_resolve(file_path)
            calendars, source = read_calendars(resolved)

            page, pagination = paginate(calendars, offset=offset, limit=limit)
            if strip:
                page = strip_empty_list(page)

            return format_response({
                "calendars": page,
                "pagination": pagination,
                "source": source,
            })
        except (MpxjError, ValueError) as exc:
            return _error_response(exc)

    logger.info("Registered 5 mpxj fast-read tools.")
