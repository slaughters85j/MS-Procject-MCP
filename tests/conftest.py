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
