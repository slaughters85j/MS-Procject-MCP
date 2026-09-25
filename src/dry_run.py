"""
MSPROJECT_DRY_RUN server-wide safety net (adapted from the 4nswer fork).

When MSPROJECT_DRY_RUN=1, all mutation tools return what they WOULD do
without executing.  Complementary to bulk_ops' per-operation dry-run mode.

The gate is applied to every mutating tool in one place, src/tool_guardrails.py,
so individual tools do not check it themselves.
"""

import json
import os


def is_dry_run() -> bool:
    """Return True if the server-wide dry-run env var is set."""
    return os.environ.get("MSPROJECT_DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on")


def dry_run_response(tool_name: str, params: dict) -> str:
    """
    Return a JSON response describing what the tool WOULD have done.

    This is the standard shape all tools should return when dry-run is active.
    """
    return json.dumps({
        "status": "dry-run",
        "tool": tool_name,
        "would_execute": params,
        "message": (
            f"MSPROJECT_DRY_RUN is active. "
            f"{tool_name} was NOT executed. "
            f"Unset the variable to allow mutations."
        ),
    }, indent=2)
