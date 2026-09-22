"""
Tests: Server Instructions + Tool Guide

Tests that:
  1. SERVER_INSTRUCTIONS is a non-empty string with batching rules.
  2. The tool guide payload has the expected structure.
  3. register_tool_guide registers a callable get_tool_guide tool.
"""

import json
from tests.fakes import FakeMCP
from src.tool_guide import (
    SERVER_INSTRUCTIONS,
    _TOOL_GUIDE,
    register_tool_guide,
)


# ---------------------------------------------------------------------------
# SERVER_INSTRUCTIONS
# ---------------------------------------------------------------------------

class TestServerInstructions:
    def test_is_nonempty_string(self):
        assert isinstance(SERVER_INSTRUCTIONS, str)
        assert len(SERVER_INSTRUCTIONS) > 100

    def test_mentions_batching_rule(self):
        assert "bulk_" in SERVER_INSTRUCTIONS.lower() or "bulk" in SERVER_INSTRUCTIONS

    def test_mentions_safe_root(self):
        assert "MSPROJECT_SAFE_ROOT" in SERVER_INSTRUCTIONS

    def test_mentions_dry_run(self):
        assert "MSPROJECT_DRY_RUN" in SERVER_INSTRUCTIONS

    def test_mentions_hardening(self):
        assert "ProjectSession" in SERVER_INSTRUCTIONS

    def test_mentions_get_tool_guide(self):
        assert "get_tool_guide" in SERVER_INSTRUCTIONS


# ---------------------------------------------------------------------------
# _TOOL_GUIDE structure
# ---------------------------------------------------------------------------

class TestToolGuidePayload:
    def test_has_efficiency_rules(self):
        assert "efficiency_rules" in _TOOL_GUIDE
        assert isinstance(_TOOL_GUIDE["efficiency_rules"], list)
        assert len(_TOOL_GUIDE["efficiency_rules"]) >= 3

    def test_has_bulk_pairs(self):
        pairs = _TOOL_GUIDE.get("bulk_pairs", {})
        assert isinstance(pairs, dict)
        assert len(pairs) >= 5
        for key, val in pairs.items():
            assert "single" in val, f"Pair {key} missing 'single'"
            assert "bulk" in val, f"Pair {key} missing 'bulk'"

    def test_has_tool_categories(self):
        cats = _TOOL_GUIDE.get("tool_categories", {})
        assert isinstance(cats, dict)
        # Must have the expected categories
        expected = {
            "project_management", "read_tasks", "write_tasks",
            "resources", "calendars", "hardening", "server_meta",
        }
        assert expected.issubset(set(cats.keys())), \
            f"Missing categories: {expected - set(cats.keys())}"

    def test_hardening_includes_session_tools(self):
        wp = _TOOL_GUIDE["tool_categories"]["hardening"]
        assert "session_info" in wp
        assert "resolve_task" in wp

    def test_server_meta_includes_guide(self):
        meta = _TOOL_GUIDE["tool_categories"]["server_meta"]
        assert "get_tool_guide" in meta
        assert "health_check" in meta

    def test_serializes_to_valid_json(self):
        text = json.dumps(_TOOL_GUIDE)
        parsed = json.loads(text)
        assert parsed == _TOOL_GUIDE


# ---------------------------------------------------------------------------
# register_tool_guide
# ---------------------------------------------------------------------------

class TestRegisterToolGuide:
    def test_registers_tool(self):
        fake = FakeMCP()
        register_tool_guide(fake)
        assert "get_tool_guide" in fake.tools

    def test_tool_returns_valid_json(self):
        fake = FakeMCP()
        register_tool_guide(fake)
        result = fake.tools["get_tool_guide"]()
        parsed = json.loads(result)
        assert "efficiency_rules" in parsed
        assert "bulk_pairs" in parsed
        assert "tool_categories" in parsed
