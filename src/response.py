"""
Response size management: paginate, strip_empty, format_response.
Adapted from devGPL fork. See BREAKING_CHANGES.md for contract details.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "paginate",
    "strip_empty",
    "format_response",
    "DEFAULT_PAGE_LIMIT",
    "COMPACT_THRESHOLD",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default page size. Callers that genuinely want everything pass limit=-1.
DEFAULT_PAGE_LIMIT = 200

# Below this byte count, use indented JSON for human readability.
COMPACT_THRESHOLD = 4096

# Identity fields — always kept even when empty, because without them the
# row cannot be identified or ordered.
_ALWAYS_KEEP = frozenset(("unique_id", "id", "name"))

# Fields where zero is a measurement, not an absence. 0% complete and zero
# slack are results; dropping them says "not started" or "no slack computed"
# which is a different claim.
_ZERO_IS_MEANINGFUL = frozenset((
    "percent_complete", "outline_level", "duration_days",
    "total_slack_days", "free_slack_days",
    "remaining_duration_days",
))


# ---------------------------------------------------------------------------
# paginate
# ---------------------------------------------------------------------------

def paginate(
    items: List[Any],
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> Tuple[List[Any], Dict[str, Any]]:
    """Slice a list and return (page, pagination_metadata).

    Args:
        items:  The full list to paginate.
        offset: Zero-based start index.
        limit:  Maximum items to return. -1 or None means "all from offset".

    Returns:
        (page, meta) where meta always has total/returned/offset and adds
        truncated=True with instructions when there are more items.
    """
    total = len(items)

    # Clamp offset to valid range
    offset = max(0, min(offset, total))

    # limit=-1 or None means uncapped
    if limit is None or limit < 0:
        effective_limit = total
    else:
        effective_limit = limit

    page = items[offset : offset + effective_limit]

    meta = {
        "total": total,
        "returned": len(page),
        "offset": offset,
    }

    if offset + len(page) < total:
        meta["truncated"] = True
        meta["next_offset"] = offset + len(page)
        meta["hint"] = "pass offset=%d for next page, limit=-1 for all" % (
            offset + len(page),
        )

    return page, meta


# ---------------------------------------------------------------------------
# strip_empty
# ---------------------------------------------------------------------------

def strip_empty(task: Dict[str, Any]) -> Dict[str, Any]:
    """Remove fields that carry no information from a task dict.

    A MISSING KEY MEANS EMPTY, ZERO OR FALSE. That is the contract.

    Keeps:
      - Identity fields (unique_id, id, name) always.
      - Fields where zero is a measurement (_ZERO_IS_MEANINGFUL).
      - Any field with a truthy, non-zero, non-empty value.

    Drops:
      - None, "", False values.
      - Zero values for fields NOT in _ZERO_IS_MEANINGFUL.
    """
    out = {}
    for key, value in task.items():
        if key in _ALWAYS_KEEP:
            out[key] = value
        elif value is None or value == "" or value is False:
            continue
        elif value == 0 and key not in _ZERO_IS_MEANINGFUL:
            continue
        else:
            out[key] = value
    return out


def strip_empty_list(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply strip_empty to every task in a list."""
    return [strip_empty(t) for t in tasks]


# ---------------------------------------------------------------------------
# format_response
# ---------------------------------------------------------------------------

def format_response(
    payload: Any,
    threshold: int = COMPACT_THRESHOLD,
) -> str:
    """Serialize a response: compact JSON above threshold, indented below.

    Small responses (below threshold bytes) are indented for human readability
    in logs and transcripts. Large responses use compact separators to minimize
    token consumption.

    Serializes compact first and only re-serializes the small ones, so the
    double pass is paid exactly where it costs nothing.
    """
    compact = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if len(compact) <= threshold:
        return json.dumps(payload, indent=2, ensure_ascii=False)
    return compact


# ---------------------------------------------------------------------------
# Convenience: full pipeline for list-of-tasks responses
# ---------------------------------------------------------------------------

def prepare_task_response(
    tasks: List[Dict[str, Any]],
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
    strip: bool = True,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """Full pipeline: paginate -> strip -> format.

    Args:
        tasks:  Complete list of task dicts (pre-sort, pre-filter).
        offset: Pagination offset.
        limit:  Page size (-1 for all).
        strip:  Whether to strip empty fields.
        extra:  Additional top-level keys to include in the response.

    Returns:
        JSON string ready to return from a tool.
    """
    page, pagination = paginate(tasks, offset=offset, limit=limit)
    if strip:
        page = strip_empty_list(page)
    result: Dict[str, Any] = {"pagination": pagination, "tasks": page}
    if extra:
        result.update(extra)
    return format_response(result)


def prepare_resource_response(
    resources: List[Dict[str, Any]],
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
    strip: bool = True,
) -> str:
    """Full pipeline for resource list responses."""
    page, pagination = paginate(resources, offset=offset, limit=limit)
    if strip:
        page = [strip_empty(r) for r in page]
    return format_response({"pagination": pagination, "resources": page})
