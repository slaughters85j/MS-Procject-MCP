"""
Live Integration Tests: Active-Project Identity

Tests project identity validation against real MS Project.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.project_identity import (
    get_active_identity,
    validate_project_target,
    ProjectMismatchError,
)


class TestProjectIdentity:
    """Real COM identity checks."""

    def test_identity_from_saved_project(self, temp_mpp):
        app, proj, path = temp_mpp
        identity = get_active_identity(app)
        assert identity is not None
        assert identity.display_name == proj.Name
        assert identity.canonical is not None
        assert len(identity.hash_id) > 0

    def test_validate_matching_project(self, temp_mpp):
        app, proj, path = temp_mpp
        identity = get_active_identity(app)
        # Validate by hash_id
        result = validate_project_target(app, identity.hash_id)
        assert result is not None

    def test_validate_by_path(self, temp_mpp):
        app, proj, path = temp_mpp
        # Validate by canonical path
        result = validate_project_target(app, path)
        assert result is not None

    def test_validate_mismatch_raises(self, temp_mpp):
        app, proj, path = temp_mpp
        with pytest.raises(ProjectMismatchError):
            validate_project_target(app, "BOGUS_NONEXISTENT_PATH")

    def test_identity_changes_on_save_as(self, temp_mpp, tmp_path):
        app, proj, path = temp_mpp
        old_identity = get_active_identity(app)

        new_path = os.path.join(str(tmp_path), "renamed_project.mpp")
        app.FileSaveAs(Name=new_path, Format=0)

        new_identity = get_active_identity(app)
        # After SaveAs, the path changes — identity should differ
        assert new_identity.canonical != old_identity.canonical
