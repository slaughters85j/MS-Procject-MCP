"""
Custom field renaming, writing, and value distribution.
"""

import json

from ..com_helpers import get_app, get_proj, _get_mpd, _parse_date, _find_task, _custom_field_id


def register_custom_fields_tools(mcp):
    """Register the custom fields tools on the FastMCP instance."""

    @mcp.tool()
    def rename_custom_fields(fields_json: str) -> str:
        """
        Rename custom text fields (Text1-Text30) to meaningful labels.
        Uses the MS Project CustomFieldRename method.

        Args:
            fields_json: JSON string — object mapping field names to display names.
                Example: '{"text1": "RAG Status", "text2": "Technology Required"}'
                Supported fields: text1-text30.
        """
        fields = json.loads(fields_json)
        app    = get_app()

        # pjCustomTaskText1 = 188743731, each subsequent +1
        BASE_TEXT_FIELD_ID = 188743731

        renamed = []
        for field_key, display_name in fields.items():
            key_lower = field_key.lower().strip()
            if not key_lower.startswith("text"):
                continue
            try:
                num = int(key_lower[4:])
                if num < 1 or num > 30:
                    continue
                field_id = BASE_TEXT_FIELD_ID + (num - 1)
                app.CustomFieldRename(field_id, display_name)
                renamed.append({"field": field_key, "display_name": display_name})
            except Exception as e:
                renamed.append({"field": field_key, "error": str(e)})

        return json.dumps({"renamed": len([r for r in renamed if "error" not in r]),
                           "results": renamed}, indent=2)


    @mcp.tool()
    def update_custom_fields(unique_id: int, fields_json: str) -> str:
        """
        Write any custom field on a task: Text1-30, Number1-20, Date1-10, Flag1-20, Duration1-10.

        Args:
            unique_id:   Task UniqueID (required).
            fields_json: JSON object mapping field names to values.
                         Example: '{"Text5": "Phase A", "Number1": 42, "Flag3": true, "Date1": "2026-06-01"}'
        """
        fields = json.loads(fields_json)
        app    = get_app()
        proj   = get_proj(app)
        mpd    = _get_mpd(proj)

        t = _find_task(proj, unique_id)
        if t is None:
            return json.dumps({"error": f"Task UniqueID {unique_id} not found."})

        changed = []
        errors  = []

        for field_name, value in fields.items():
            try:
                # Validate field name and get the type
                _field_id, field_type = _custom_field_id(field_name)

                # Normalize the property name for setattr (e.g. "text5" -> "Text5")
                prop_name = field_type.capitalize() + field_name[len(field_type):]

                if field_type == "date":
                    value = _parse_date(value)
                elif field_type == "flag":
                    value = bool(value)
                elif field_type == "duration":
                    value = float(value) * mpd
                elif field_type == "number":
                    value = float(value)
                else:
                    value = str(value)

                setattr(t, prop_name, value)
                changed.append({"field": field_name, "value": str(value)})
            except Exception as e:
                errors.append({"field": field_name, "error": str(e)})

        app.FileSave()
        return json.dumps({
            "status":    "updated",
            "unique_id": unique_id,
            "name":      t.Name,
            "changed":   changed,
            "errors":    errors,
        }, indent=2)


    @mcp.tool()
    def get_custom_field_values(field_name: str) -> str:
        """
        Get all unique values for a custom field across all tasks.
        Useful for validation, audit, and understanding what values exist.

        Args:
            field_name: Custom field name, e.g. 'Text1', 'Number1', 'Flag3'.
        """
        try:
            _field_id, field_type = _custom_field_id(field_name)
        except ValueError as e:
            return json.dumps({"error": str(e)})

        # Normalize property name (e.g. "text1" -> "Text1")
        prop_name = field_type.capitalize() + field_name.strip()[len(field_type):]

        app  = get_app()
        proj = get_proj(app)

        value_counts = {}
        total = 0

        for t in proj.Tasks:
            if t is None:
                continue
            total += 1
            try:
                val = getattr(t, prop_name, None)
                if val is None:
                    val = "(blank)"
                val = str(val).strip()
                if not val:
                    val = "(blank)"
            except Exception:
                val = "(error)"
            value_counts[val] = value_counts.get(val, 0) + 1

        unique_values = sorted(value_counts.keys())

        return json.dumps({
            "field":         field_name,
            "unique_values": unique_values,
            "value_counts":  value_counts,
            "total_tasks":   total,
        }, indent=2)
