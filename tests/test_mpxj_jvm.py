"""
Unit tests for mpxj_jvm: file validation, availability check, JVM lifecycle
and the Mpxj error hierarchy.
All tests use mocked mpxj/jpype, so no JVM or Java is required.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from src.mpxj_jvm import (
    MpxjError,
    MpxjFileError,
    MpxjNotAvailableError,
    MpxjParseError,
    _VALID_EXTENSIONS,
    _validate_file,
    is_mpxj_available,
)


class TestValidateFile:
    def test_valid_mpp_file(self, tmp_mpp):
        result = _validate_file(tmp_mpp)
        assert os.path.isabs(result)
        assert result.endswith(".mpp")

    def test_empty_path_raises(self):
        with pytest.raises(MpxjFileError, match="file_path is required"):
            _validate_file("")

    def test_whitespace_path_raises(self):
        with pytest.raises(MpxjFileError, match="file_path is required"):
            _validate_file("   ")

    def test_nonexistent_file_raises(self):
        with pytest.raises(MpxjFileError, match="File not found"):
            _validate_file("/nonexistent/path/project.mpp")

    def test_directory_raises(self, tmp_path):
        with pytest.raises(MpxjFileError, match="Not a file"):
            _validate_file(str(tmp_path))

    @pytest.mark.skipif(
        sys.platform == "win32", reason="chmod has no effect on Windows"
    )
    def test_unreadable_file_raises(self, tmp_mpp_readonly):
        with pytest.raises(MpxjFileError, match="not readable"):
            _validate_file(tmp_mpp_readonly)

    def test_wrong_extension_raises(self, tmp_path):
        f = tmp_path / "project.xlsx"
        f.write_bytes(b"data")
        with pytest.raises(MpxjFileError, match="Unsupported file extension"):
            _validate_file(str(f))

    def test_all_valid_extensions(self, tmp_path):
        for ext in _VALID_EXTENSIONS:
            f = tmp_path / f"test{ext}"
            f.write_bytes(b"data")
            result = _validate_file(str(f))
            assert result.endswith(ext)


class TestIsMpxjAvailable:
    def test_returns_false_when_not_installed(self):
        with patch.dict(sys.modules, {"mpxj": None, "jpype": None}):
            # Force import error
            with patch("builtins.__import__", side_effect=ImportError):
                assert is_mpxj_available() is False

    def test_returns_true_when_installed(self):
        mock_mpxj = MagicMock()
        mock_jpype = MagicMock()
        with patch.dict(sys.modules, {"mpxj": mock_mpxj, "jpype": mock_jpype}):
            assert is_mpxj_available() is True


class TestExceptionHierarchy:
    def test_all_inherit_from_mpxj_error(self):
        assert issubclass(MpxjNotAvailableError, MpxjError)
        assert issubclass(MpxjFileError, MpxjError)
        assert issubclass(MpxjParseError, MpxjError)

    def test_mpxj_error_inherits_from_exception(self):
        assert issubclass(MpxjError, Exception)

    def test_errors_have_messages(self):
        e = MpxjFileError("test message")
        assert str(e) == "test message"


class TestJVMLifecycle:
    @patch("src.mpxj_jvm._jvm_started", False)
    def test_ensure_jvm_raises_when_jpype_missing(self):
        from src.mpxj_jvm import _ensure_jvm

        with patch.dict(sys.modules, {"jpype": None}):
            with patch("builtins.__import__", side_effect=ImportError("no jpype")):
                with pytest.raises(MpxjNotAvailableError, match="jpype1 is not installed"):
                    _ensure_jvm()

    @patch("src.mpxj_jvm._jvm_started", True)
    def test_ensure_jvm_noop_when_started(self):
        from src.mpxj_jvm import _ensure_jvm
        # Should not raise
        _ensure_jvm()
