"""
Custom field renaming, writing, and value distribution.

Field IDs come from MS Project itself (Application.FieldNameToFieldConstant): the pjCustomTask*
constants are not contiguous, so arithmetic on a base ID renames or writes the wrong field.
"""

import json

from ..com_helpers import get_app, get_proj, _get_mpd, _find_task, _custom_field_id
from ..com_write import to_com_date, commit


def _parse_object(text, what):
    data = json.loads(text)
    if not isinstance(data, dict) or not data:
        raise ValueError(f"{what} must be a non-empty JSON object.")
    return data


def _convert(proj, field_type, value):
    """Convert a user value for a custom field of the given type. Raises ValueError."""
    if field_type == "date":
        return to_com_date(proj, str(value), field="date value")
    if field_type == "flag":
        if not isinstance(value, bool):
            raise ValueError(f"Flag values must be true or false (got {value!r}).")
        return value
    if field_type == "duration":
        return round(float(value) * _get_mpd(proj))
    if field_type == "number":
        return float(value)
    return str(value)


def register_custom_fields_tools(mcp):
    """Register the custom fields tools on the FastMCP instance."""

    @mcp.tool()
    def rename_custom_fields(fields_json: str) -> str:
        """
        Give custom task fields (Text1-30, Number1-20, Date1-10, Flag1-20, Duration1-10)
        meaningful display names. All keys are validated before any field is renamed.

        Args:
            fields_json: JSON string — object mapping field names to display names.
                Example: '{"text1": "RAG Status", "number1": "Risk Score"}'
        """
        fields = _parse_object(fields_json, "fields_json")
        app  = get_app()
        proj = get_proj(app)
        planned = []
        for key, display_name in fields.items():
            field_id, _type, canonical = _custom_field_id(app, key)
            if not str(display_name).strip():
                raise ValueError(f"Display name for {canonical} cannot be empty.")
            planned.append((field_id, canonical, str(display_name)))
        for field_id, _canonical, display_name in planned:
            app.CustomFieldRename(field_id, display_name)
        commit(app, proj)
        return json.dumps({"renamed": len(planned),
                           "results": [{"field": c, "display_name": d, "actual": app.CustomFieldGetName(i)}
                                       for i, c, d in planned]}, indent=2)

    @mcp.tool()
    def update_custom_fields(unique_id: int, fields_json: str) -> str:
        """
        Write custom fields on a task: Text1-30, Number1-20, Date1-10, Flag1-20, Duration1-10.
        Every field and value is validated first; nothing is written if any is invalid.

        Args:
            unique_id:   Task UniqueID (required).
            fields_json: JSON object mapping field names to values. Duration values are in days.
                         Example: '{"Text5": "Phase A", "Number1": 42, "Flag3": true, "Date1": "2026-06-01"}'
        """
        fields = _parse_object(fields_json, "fields_json")
        app  = get_app()
        proj = get_proj(app)
        t = _find_task(proj, unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})
        planned = []
        for key, value in fields.items():
            _id, field_type, canonical = _custom_field_id(app, key)
            try:
                planned.append((canonical, _convert(proj, field_type, value)))
            except (TypeError, ValueError) as e:
                raise ValueError(f"{canonical}: {e}") from e
        for canonical, value in planned:
            setattr(t, canonical, value)
        commit(app, proj)
        return json.dumps({"status": "updated", "unique_id": unique_id, "name": t.Name,
                           "changed": [{"field": c, "value": str(getattr(t, c))} for c, _ in planned],
                           "errors": []}, indent=2)  # validation is all-or-nothing; kept for compatibility

    @mcp.tool()
    def get_custom_field_values(field_name: str) -> str:
        """
        Get all unique values for a custom field across all tasks.
        Useful for validation, audit, and understanding what values exist.

        Args:
            field_name: Custom field name, e.g. 'Text1', 'Number1', 'Flag3'.
        """
        app  = get_app()
        proj = get_proj(app)
        _id, _type, prop_name = _custom_field_id(app, field_name)
        value_counts, total = {}, 0
        for t in proj.Tasks:
            if t is None:
                continue
            total += 1
            val = str(getattr(t, prop_name) or "").strip() or "(blank)"
            value_counts[val] = value_counts.get(val, 0) + 1
        return json.dumps({"field": prop_name, "display_name": app.CustomFieldGetName(_id) or None,
                           "unique_values": sorted(value_counts), "value_counts": value_counts,
                           "total_tasks": total}, indent=2)
