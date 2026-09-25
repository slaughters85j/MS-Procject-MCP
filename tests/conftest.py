"""
Shared pytest fixtures for the unit tests.
"""

import os

import pytest


@pytest.fixture
def tmp_mpp(tmp_path):
    """Create a temporary .mpp file for testing."""
    f = tmp_path / "test_project.mpp"
    f.write_bytes(b"fake mpp content")
    return str(f)


@pytest.fixture
def tmp_mpp_readonly(tmp_path):
    """Create a read-only .mpp file."""
    f = tmp_path / "readonly.mpp"
    f.write_bytes(b"fake mpp content")
    os.chmod(str(f), 0o000)
    yield str(f)
    os.chmod(str(f), 0o644)


@pytest.fixture
def reset_ui_state(monkeypatch):
    """Module-level UI state must not leak between tests."""
    from src import ui_lock
    monkeypatch.setattr(ui_lock, "_configured_mode", None)
    monkeypatch.setattr(ui_lock, "_active_lock", None)
    monkeypatch.setattr(ui_lock, "_last_restore_error", None)
