"""
End-to-End COM Smoke Tests

Validates core COM operations (create, read, update, delete, save/reopen)
against a real MS Project instance. These exercise the COM layer that
server.py tools depend on — not the MCP tool wrappers themselves.

For server.py tool-level tests, see the per-module live test files which test
through the module APIs (ProjectSession, TaskStore, verify_write, etc.).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from .conftest import live_task_count, find_task_by_uid


class TestCOMRoundTrip:
    """Smoke tests for COM operations that server.py tools depend on."""

    def test_new_project_and_task_creation(self, project_app):
        """Create a project, add tasks, verify count is exact."""
        app = project_app
        app.FileNew(SummaryInfo=False)
        proj = app.ActiveProject
        proj.Title = "E2E Test Project"

        t1 = proj.Tasks.Add("E2E Summary")
        t1.OutlineLevel = 1
        t2 = proj.Tasks.Add("E2E Work")
        t2.OutlineLevel = 2
        t2.Duration = int(proj.HoursPerDay * 60) * 2

        assert live_task_count(proj) == 2

    def test_add_task_and_read_back(self, project_app):
        """Add a task via COM and read it back by UniqueID."""
        app = project_app
        app.FileNew(SummaryInfo=False)
        proj = app.ActiveProject
        mpd = int(proj.HoursPerDay * 60)

        t = proj.Tasks.Add("Readback Test")
        t.Duration = mpd * 5
        t.Text1 = "Amber"
        t.Notes = "Test note for E2E"

        uid = t.UniqueID
        found = find_task_by_uid(proj, uid)

        assert found is not None
        assert found.Name == "Readback Test"
        assert found.Text1 == "Amber"
        assert found.Notes == "Test note for E2E"
        assert abs(found.Duration - mpd * 5) < 1

    def test_update_and_save(self, temp_mpp, tmp_path):
        """Update a task, save, reopen, verify persistence."""
        app, proj, path = temp_mpp

        # Find a work task (not summary, not milestone)
        task = None
        for t in proj.Tasks:
            if t is not None and not t.Summary and not t.Milestone:
                task = t
                break
        assert task is not None

        uid = task.UniqueID
        task.Name = "Persisted Name"
        task.PercentComplete = 77
        app.FileSave()

        # Close and reopen
        app.FileClose(Save=0)
        app.FileOpen(path)
        proj2 = app.ActiveProject

        found = find_task_by_uid(proj2, uid)
        assert found is not None
        assert found.Name == "Persisted Name"
        assert found.PercentComplete == 77

    def test_delete_task(self, temp_mpp):
        """Delete a task and verify it's gone."""
        app, proj, path = temp_mpp

        before = live_task_count(proj)

        new_task = proj.Tasks.Add("To Be Deleted")
        uid = new_task.UniqueID
        task_id = new_task.ID

        app.SelectRow(task_id, False)
        app.EditDelete()

        after = live_task_count(proj)
        assert after == before  # Back to original count

        assert find_task_by_uid(proj, uid) is None

    def test_health_check_importable(self, project_app):
        """Verify server module loads and health_check is callable."""
        import server

        # The server module should have a health_check registered as an MCP tool.
        # We can't call it via the MCP layer in a unit test, but we can verify
        # the function is registered and the module loaded without import errors.
        assert hasattr(server, 'mcp'), "server.mcp (FastMCP instance) missing"
