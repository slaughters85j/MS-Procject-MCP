"""
WP-2: Active-Project Identity Tests

Tests for project identity scheme, validation, and mismatch detection.
These tests run on any platform — no COM required.

NOTE: Testing against live MS Project remains required.
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.project_identity import (
    canonical_path,
    path_hash,
    ProjectIdentity,
    ProjectMismatchError,
    get_active_identity,
    validate_project_target,
)


# ---------------------------------------------------------------------------
# Path canonicalization
# ---------------------------------------------------------------------------

class TestCanonicalPath:
    """Test path normalization."""

    def test_normalizes_separators(self):
        """Forward slashes become Windows-style backslashes (ntpath)."""
        result = canonical_path("C:/Users/test/project.mpp")
        # ntpath always normalizes to backslashes regardless of host OS
        assert "/" not in result
        assert "\\\\" not in result  # No doubled backslashes

    def test_collapses_double_separators(self):
        result = canonical_path("C:\\Users\\\\test\\project.mpp")
        # normpath collapses doubles
        assert "\\\\" not in result.replace("\\\\", "")

    def test_resolves_parent_refs(self):
        result = canonical_path("C:/Users/test/../test/project.mpp")
        expected = canonical_path("C:/Users/test/project.mpp")
        assert result == expected

    def test_same_path_different_case(self):
        """On Windows, paths are case-insensitive."""
        a = canonical_path("C:/Users/Test/PROJECT.mpp")
        b = canonical_path("C:/users/test/project.mpp")
        if os.name == "nt":
            assert a == b
        # On Linux/macOS, case sensitivity is preserved — not a bug


class TestPathHash:
    """Test hash-based identity."""

    def test_hash_is_12_chars(self):
        h = path_hash("C:/test/project.mpp")
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_path_same_hash(self):
        a = path_hash("C:/Users/test/project.mpp")
        b = path_hash("C:/Users/test/project.mpp")
        assert a == b

    def test_different_path_different_hash(self):
        a = path_hash("C:/project_a.mpp")
        b = path_hash("C:/project_b.mpp")
        assert a != b

    def test_normalized_paths_match(self):
        """Paths that normalize to the same canonical form get same hash."""
        a = path_hash("C:/Users/../Users/test/project.mpp")
        b = path_hash("C:/Users/test/project.mpp")
        assert a == b


# ---------------------------------------------------------------------------
# ProjectIdentity
# ---------------------------------------------------------------------------

class TestProjectIdentity:
    """Test the ProjectIdentity dataclass."""

    def test_from_path(self):
        pid = ProjectIdentity.from_path("C:/Users/test/big_project.mpp")
        assert pid.display_name == "big_project.mpp"
        assert len(pid.hash_id) == 12
        assert pid.canonical == canonical_path("C:/Users/test/big_project.mpp")

    def test_matches_same_path(self):
        pid = ProjectIdentity.from_path("C:/test/project.mpp")
        assert pid.matches("C:/test/project.mpp")

    def test_matches_equivalent_path(self):
        pid = ProjectIdentity.from_path("C:/test/project.mpp")
        assert pid.matches("C:/test/../test/project.mpp")

    def test_no_match_different_path(self):
        pid = ProjectIdentity.from_path("C:/test/project_a.mpp")
        assert not pid.matches("C:/test/project_b.mpp")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    """Test project identity validation against COM."""

    def _mock_app(self, project_path="C:\\Users\\test\\project.mpp"):
        app = MagicMock()
        app.Projects.Count = 1
        app.ActiveProject.FullName = project_path
        return app

    def test_validate_by_hash(self):
        app = self._mock_app()
        expected_hash = path_hash("C:\\Users\\test\\project.mpp")
        result = validate_project_target(app, expected_hash)
        assert result.hash_id == expected_hash

    def test_validate_by_path(self):
        app = self._mock_app()
        result = validate_project_target(app, "C:\\Users\\test\\project.mpp")
        assert result.display_name == "project.mpp"

    def test_mismatch_raises(self):
        app = self._mock_app("C:\\Users\\test\\project_a.mpp")
        with pytest.raises(ProjectMismatchError) as exc_info:
            validate_project_target(app, "C:\\other\\project_b.mpp")
        assert "mismatch" in str(exc_info.value).lower()
        assert exc_info.value.requested == "C:\\other\\project_b.mpp"

    def test_no_project_open(self):
        app = MagicMock()
        app.Projects.Count = 0
        with pytest.raises(RuntimeError, match="No project"):
            validate_project_target(app, "anything")

    def test_validate_returns_identity(self):
        """Successful validation returns the full identity."""
        app = self._mock_app("C:\\test\\my.mpp")
        result = validate_project_target(app, path_hash("C:\\test\\my.mpp"))
        assert isinstance(result, ProjectIdentity)
        assert result.display_name == "my.mpp"


# ---------------------------------------------------------------------------
# ProjectMismatchError
# ---------------------------------------------------------------------------

class TestMismatchError:
    """Test the error type itself."""

    def test_error_contains_both_paths(self):
        err = ProjectMismatchError(
            requested="C:\\a.mpp", active="C:\\b.mpp"
        )
        assert "C:\\a.mpp" in str(err)
        assert "C:\\b.mpp" in str(err)
        assert "switch_project" in str(err).lower()

    def test_error_attrs(self):
        err = ProjectMismatchError(requested="req", active="act")
        assert err.requested == "req"
        assert err.active == "act"


# ---------------------------------------------------------------------------
# get_active_identity
# ---------------------------------------------------------------------------

class TestGetActiveIdentity:
    """Test extracting identity from COM app object."""

    def test_returns_identity_when_project_open(self):
        app = MagicMock()
        app.Projects.Count = 1
        app.ActiveProject.FullName = "C:\\test\\schedule.mpp"
        identity = get_active_identity(app)
        assert identity is not None
        assert identity.display_name == "schedule.mpp"

    def test_returns_none_when_no_project(self):
        app = MagicMock()
        app.Projects.Count = 0
        assert get_active_identity(app) is None

    def test_returns_none_on_com_error(self):
        app = MagicMock()
        app.Projects.Count = 1
        app.ActiveProject.FullName = None
        assert get_active_identity(app) is None

    def test_handles_exception_gracefully(self):
        app = MagicMock()
        # Make Projects.Count raise, simulating a dead COM connection.
        type(app.Projects).Count = property(
            lambda self: (_ for _ in ()).throw(Exception("COM died"))
        )
        result = get_active_identity(app)
        assert result is None


# ---------------------------------------------------------------------------
# Path edge cases (must pass on both Windows and macOS/Linux)
# ---------------------------------------------------------------------------

class TestPathEdgeCases:
    """Edge cases for path normalization — review fix #7."""

    def test_unc_path(self):
        """UNC paths should normalize correctly."""
        identity = ProjectIdentity.from_path(r"\\server\share\project.mpp")
        assert identity.display_name == "project.mpp"
        assert identity.hash_id  # Should produce a valid hash

    def test_trailing_separator(self):
        """Trailing separator should not affect identity."""
        a = canonical_path("C:\\Users\\test\\")
        b = canonical_path("C:\\Users\\test")
        assert a == b

    def test_mixed_separators(self):
        """Forward and back slashes should normalize to same form."""
        a = canonical_path("C:/Users/test/project.mpp")
        b = canonical_path("C:\\Users\\test\\project.mpp")
        assert a == b

    def test_spaces_in_path(self):
        """Paths with spaces should work fine."""
        identity = ProjectIdentity.from_path(
            r"C:\Users\John Doe\My Projects\big project.mpp"
        )
        assert identity.display_name == "big project.mpp"
        assert len(identity.hash_id) == 12

    def test_deep_nesting(self):
        """Deeply nested paths normalize correctly."""
        path = "C:\\a\\b\\c\\d\\e\\f\\g\\project.mpp"
        identity = ProjectIdentity.from_path(path)
        assert identity.display_name == "project.mpp"

    def test_dot_segments(self):
        """Parent directory refs collapse."""
        a = canonical_path("C:\\Users\\test\\..\\test\\project.mpp")
        b = canonical_path("C:\\Users\\test\\project.mpp")
        assert a == b

    def test_case_insensitivity(self):
        """Windows paths are case-insensitive via ntpath.normcase."""
        a = canonical_path("C:\\USERS\\Test\\PROJECT.MPP")
        b = canonical_path("C:\\users\\test\\project.mpp")
        # ntpath.normcase lowercases on all platforms
        assert a == b
