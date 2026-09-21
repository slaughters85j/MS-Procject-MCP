"""
Tests for MSPROJECT_DRY_RUN server-wide safety net (Sprint 1).
"""

import os
import sys
import json
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.dry_run import is_dry_run, dry_run_response


class TestDryRun:
    """Unit tests for src.dry_run module."""

    def test_not_dry_run_when_unset(self, monkeypatch):
        monkeypatch.delenv("MSPROJECT_DRY_RUN", raising=False)
        assert not is_dry_run()

    def test_dry_run_when_1(self, monkeypatch):
        monkeypatch.setenv("MSPROJECT_DRY_RUN", "1")
        assert is_dry_run()

    def test_dry_run_when_true(self, monkeypatch):
        monkeypatch.setenv("MSPROJECT_DRY_RUN", "true")
        assert is_dry_run()

    def test_dry_run_when_yes(self, monkeypatch):
        monkeypatch.setenv("MSPROJECT_DRY_RUN", "yes")
        assert is_dry_run()

    def test_not_dry_run_when_0(self, monkeypatch):
        monkeypatch.setenv("MSPROJECT_DRY_RUN", "0")
        assert not is_dry_run()

    def test_not_dry_run_when_empty(self, monkeypatch):
        monkeypatch.setenv("MSPROJECT_DRY_RUN", "")
        assert not is_dry_run()

    def test_not_dry_run_with_whitespace(self, monkeypatch):
        monkeypatch.setenv("MSPROJECT_DRY_RUN", "  ")
        assert not is_dry_run()

    def test_response_shape(self):
        result = json.loads(dry_run_response("save_project", {"format": "mpp"}))
        assert result["status"] == "dry-run"
        assert result["tool"] == "save_project"
        assert result["would_execute"] == {"format": "mpp"}
        assert "NOT executed" in result["message"]

    def test_response_includes_tool_name(self):
        result = json.loads(dry_run_response("delete_task", {"unique_id": 42}))
        assert "delete_task" in result["message"]
        assert result["would_execute"]["unique_id"] == 42
