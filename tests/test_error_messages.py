"""
Tests: get_app() error messages

Verifies that get_app() error messages include the three diagnostic
failure modes: not running, elevated shell, wrong logon session.
"""

import pytest


def _make_server_module():
    """Return the module that owns get_app, so patching its _find_app exercises get_app
    without live COM. It loads on all platforms because COM imports are deferred inside
    function bodies."""
    from src import com_helpers
    return com_helpers


class TestGetAppErrorMessages:
    def test_not_attached_message_mentions_three_causes(self):
        server = _make_server_module()
        # Force _find_app to return None
        original = server._find_app
        server._find_app = lambda: None
        try:
            with pytest.raises(RuntimeError) as exc_info:
                server.get_app()
            msg = str(exc_info.value)
            # Must mention all three failure modes
            assert "running" in msg.lower(), "Should mention MS Project not running"
            assert "elevated" in msg.lower() or "admin" in msg.lower(), \
                "Should mention elevated/admin shell"
            assert "logon session" in msg.lower() or "ssh" in msg.lower(), \
                "Should mention wrong logon session or SSH"
        finally:
            server._find_app = original

    def test_no_project_open_message(self):
        """When app is found but no project is open."""
        server = _make_server_module()

        class FakeAppNoProjects:
            class Projects:
                Count = 0

        original = server._find_app
        server._find_app = lambda: FakeAppNoProjects()
        try:
            with pytest.raises(RuntimeError) as exc_info:
                server.get_app(require_project=True)
            msg = str(exc_info.value)
            assert "no project" in msg.lower() or "open" in msg.lower()
        finally:
            server._find_app = original

    def test_get_app_succeeds_with_project(self):
        """When app is found and project is open, returns the app."""
        server = _make_server_module()

        class FakeAppWithProject:
            class Projects:
                Count = 1

        original = server._find_app
        server._find_app = lambda: FakeAppWithProject()
        try:
            app = server.get_app(require_project=True)
            assert app is not None
        finally:
            server._find_app = original
