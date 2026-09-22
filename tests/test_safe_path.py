"""
Tests for MSPROJECT_SAFE_ROOT path confinement.
"""

import os
import sys
import tempfile
import pytest

# Ensure src/ is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSafePath:
    """Unit tests for src.safe_path module."""

    def _reload(self):
        """Force reimport of safe_path after env change."""
        import importlib
        if "src.safe_path" in sys.modules:
            importlib.reload(sys.modules["src.safe_path"])
        from src.safe_path import validate_safe_path, is_confined, get_safe_root, reload_safe_root
        reload_safe_root()
        return validate_safe_path, is_confined, get_safe_root

    def test_no_confinement_when_unset(self, monkeypatch):
        """Without MSPROJECT_SAFE_ROOT, paths pass through unchanged."""
        monkeypatch.delenv("MSPROJECT_SAFE_ROOT", raising=False)
        validate, confined, root = self._reload()
        assert not confined()
        assert root() is None
        assert validate("/any/path/file.mpp") == "/any/path/file.mpp"

    def test_confined_when_set(self, monkeypatch, tmp_path):
        """With MSPROJECT_SAFE_ROOT set to a valid dir, confinement is active."""
        monkeypatch.setenv("MSPROJECT_SAFE_ROOT", str(tmp_path))
        validate, confined, root = self._reload()
        assert confined()
        assert root() == str(tmp_path)

    def test_path_inside_root_passes(self, monkeypatch, tmp_path):
        """A path under the safe root resolves and passes validation."""
        monkeypatch.setenv("MSPROJECT_SAFE_ROOT", str(tmp_path))
        validate, _, _ = self._reload()
        inner = tmp_path / "projects" / "test.mpp"
        inner.parent.mkdir(parents=True, exist_ok=True)
        inner.touch()
        result = validate(str(inner))
        assert os.path.realpath(str(inner)) == result

    def test_path_outside_root_rejected(self, monkeypatch, tmp_path):
        """A path outside the safe root raises ValueError."""
        monkeypatch.setenv("MSPROJECT_SAFE_ROOT", str(tmp_path))
        validate, _, _ = self._reload()
        with pytest.raises(ValueError, match="Path confinement violation"):
            validate("/etc/passwd")

    def test_traversal_rejected(self, monkeypatch, tmp_path):
        """Directory traversal (../) is caught after realpath resolution."""
        monkeypatch.setenv("MSPROJECT_SAFE_ROOT", str(tmp_path))
        validate, _, _ = self._reload()
        sneaky = os.path.join(str(tmp_path), "subdir", "..", "..", "etc", "passwd")
        with pytest.raises(ValueError, match="Path confinement violation"):
            validate(sneaky)

    def test_symlink_resolved(self, monkeypatch, tmp_path):
        """Symlinks pointing outside the safe root are rejected."""
        monkeypatch.setenv("MSPROJECT_SAFE_ROOT", str(tmp_path))
        validate, _, _ = self._reload()
        # Create a symlink inside tmp_path that points to /tmp
        link = tmp_path / "escape_link"
        try:
            link.symlink_to(tempfile.gettempdir())
        except OSError:
            pytest.skip("Cannot create symlinks on this platform/permissions")
        target = os.path.join(str(link), "somefile.mpp")
        with pytest.raises(ValueError, match="Path confinement violation"):
            validate(target)

    def test_root_dir_itself_passes(self, monkeypatch, tmp_path):
        """The safe root directory itself is a valid path."""
        monkeypatch.setenv("MSPROJECT_SAFE_ROOT", str(tmp_path))
        validate, _, _ = self._reload()
        result = validate(str(tmp_path))
        assert result == os.path.realpath(str(tmp_path))
