"""
Idempotent Bulk Operations — tests for bulk_tools: item JSON parsing and
the registered bulk_update / bulk_status tools.

All tests run on macOS without COM via mocks.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.bulk_ops import BulkAction
from src.bulk_tools import _parse_items
from tests._bulk_helpers import _make_task, _make_store


# ---------------------------------------------------------------------------
# Parse items (bulk_tools)
# ---------------------------------------------------------------------------

class TestParseItems:
    def test_valid_json(self):
        raw = json.dumps([
            {"action": "update", "target_uid": 1, "fields": {"Name": "x"}}
        ])
        items = _parse_items(raw)
        assert len(items) == 1
        assert items[0].action == BulkAction.UPDATE
        assert items[0].target_uid == 1

    def test_invalid_json(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            _parse_items("not json{{{")

    def test_not_array(self):
        with pytest.raises(ValueError, match="JSON array"):
            _parse_items('{"action": "update"}')

    def test_unknown_action(self):
        raw = json.dumps([{"action": "explode", "target_uid": 1,
                           "fields": {"x": 1}}])
        with pytest.raises(ValueError, match="unknown action"):
            _parse_items(raw)

    def test_bad_uid_type(self):
        raw = json.dumps([{"action": "update", "target_uid": "abc",
                           "fields": {"x": 1}}])
        with pytest.raises(ValueError, match="integer"):
            _parse_items(raw)

    def test_item_not_object(self):
        raw = json.dumps(["just a string"])
        with pytest.raises(ValueError, match="expected object"):
            _parse_items(raw)

    def test_fields_not_dict(self):
        raw = json.dumps([{"action": "update", "target_uid": 1,
                           "fields": "not a dict"}])
        with pytest.raises(ValueError, match="fields must be an object"):
            _parse_items(raw)

    def test_empty_array(self):
        """Empty JSON array is valid parse, validation catches it later."""
        items = _parse_items("[]")
        assert items == []

    def test_multiple_items(self):
        raw = json.dumps([
            {"action": "update", "target_uid": 1, "fields": {"Name": "a"}},
            {"action": "update", "target_uid": 2, "fields": {"Name": "b"}},
        ])
        items = _parse_items(raw)
        assert len(items) == 2
        assert items[0].target_uid == 1
        assert items[1].target_uid == 2

    def test_missing_fields_key_defaults_empty(self):
        """Omitting 'fields' key defaults to empty dict."""
        raw = json.dumps([{"action": "update", "target_uid": 1}])
        items = _parse_items(raw)
        assert items[0].fields == {}

    def test_target_uid_none(self):
        """target_uid can be None (for insert actions eventually)."""
        raw = json.dumps([{"action": "update", "fields": {"Name": "x"}}])
        items = _parse_items(raw)
        assert items[0].target_uid is None

    def test_missing_action_key(self):
        """Missing 'action' key gives a clear error, not 'unknown action'."""
        raw = json.dumps([{"target_uid": 1, "fields": {"Name": "x"}}])
        with pytest.raises(ValueError, match="missing required 'action'"):
            _parse_items(raw)


# ---------------------------------------------------------------------------
# Tool-level edge cases (bulk_update via register_bulk_tools)
# ---------------------------------------------------------------------------

class TestBulkUpdateTool:
    """Test the registered bulk_update tool function at the tool level."""

    def _get_tool(self):
        """Register bulk tools on a mock MCP and return the bulk_update fn."""
        from src.bulk_tools import register_bulk_tools
        mock_mcp = MagicMock()
        # Capture the decorated functions
        registered = {}
        def tool_decorator():
            def wrapper(fn):
                registered[fn.__name__] = fn
                return fn
            return wrapper
        mock_mcp.tool = tool_decorator
        register_bulk_tools(mock_mcp)
        return registered["bulk_update"], registered.get("bulk_status")

    def test_empty_items_returns_validation_error(self):
        """Empty array parses, but validate_bulk_items rejects it."""
        bulk_update, _ = self._get_tool()
        with patch("src.bulk_tools.get_session") as gs, \
             patch("src.bulk_tools.get_store") as gst:
            session = MagicMock()
            session.is_attached = True
            session.app = MagicMock()
            session.app.ActiveProject = MagicMock()
            gs.return_value = session
            gst.return_value = MagicMock()

            result = bulk_update(items="[]", mode="dry_run")
            # Validation catches empty list — failed count is at least 1
            assert result["total"] == 0
            assert result["failed"] >= 1
            assert len(result["items"]) == 1
            assert result["items"][0]["status"] == "error"
            assert "empty" in result["items"][0]["error"]

    def test_single_item_dry_run(self):
        """Single-item dry_run goes through the full path."""
        bulk_update, _ = self._get_tool()
        task = _make_task(1, Name="Old")
        store = _make_store({1: task})
        with patch("src.bulk_tools.get_session") as gs, \
             patch("src.bulk_tools.get_store", return_value=store):
            session = MagicMock()
            session.is_attached = True
            session.app = MagicMock()
            session.app.ActiveProject = MagicMock()
            gs.return_value = session

            raw = json.dumps([
                {"action": "update", "target_uid": 1, "fields": {"Name": "New"}}
            ])
            result = bulk_update(items=raw, mode="dry_run")
            assert result["mode"] == "dry_run"
            assert result["total"] == 1
            assert result["succeeded"] == 1

    def test_all_skipped_scenario(self):
        """Every item already matches -> all skipped, zero succeeded."""
        bulk_update, _ = self._get_tool()
        t1 = _make_task(1, Name="Same1")
        t2 = _make_task(2, Name="Same2")
        store = _make_store({1: t1, 2: t2})
        with patch("src.bulk_tools.get_session") as gs, \
             patch("src.bulk_tools.get_store", return_value=store):
            session = MagicMock()
            session.is_attached = True
            session.app = MagicMock()
            session.app.ActiveProject = MagicMock()
            gs.return_value = session

            raw = json.dumps([
                {"action": "update", "target_uid": 1, "fields": {"Name": "Same1"}},
                {"action": "update", "target_uid": 2, "fields": {"Name": "Same2"}},
            ])
            result = bulk_update(items=raw, mode="dry_run")
            assert result["total"] == 2
            assert result["skipped"] == 2
            assert result["succeeded"] == 0
            assert result["failed"] == 0

    def test_invalid_mode(self):
        """Invalid mode returns error dict immediately."""
        bulk_update, _ = self._get_tool()
        result = bulk_update(items="[]", mode="yolo")
        assert "error" in result
        assert "mode" in result["error"]

    def test_session_not_attached(self):
        """Detached session returns readable error."""
        bulk_update, _ = self._get_tool()
        with patch("src.bulk_tools.get_session") as gs:
            session = MagicMock()
            session.is_attached = False
            gs.return_value = session
            result = bulk_update(
                items='[{"action":"update","target_uid":1,"fields":{"Name":"x"}}]',
                mode="dry_run",
            )
            assert "error" in result
            assert "session" in result["error"].lower() or "attach" in result["error"].lower()

    def test_bulk_status_before_any_run(self):
        """bulk_status before any run returns informative message."""
        import src.bulk_tools as bt
        bt._last_result = None
        _, bulk_status = self._get_tool()
        result = bulk_status()
        assert "no bulk" in result.get("status", "").lower()
