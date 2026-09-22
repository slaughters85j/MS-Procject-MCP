"""
Tests for pyproject.toml packaging.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestPackaging:
    """Verify pyproject.toml and requirements.txt consistency."""

    def test_pyproject_exists(self):
        assert os.path.exists(os.path.join(PROJECT_ROOT, "pyproject.toml"))

    def test_pyproject_has_console_script(self):
        toml_path = os.path.join(PROJECT_ROOT, "pyproject.toml")
        with open(toml_path, "r") as f:
            content = f.read()
        assert 'msproject-mcp = "server:main"' in content

    def test_pyproject_has_mcp_ceiling(self):
        """mcp version ceiling prevents ARM64 cryptography build failure."""
        toml_path = os.path.join(PROJECT_ROOT, "pyproject.toml")
        with open(toml_path, "r") as f:
            content = f.read()
        assert "mcp>=1.0,<1.20" in content

    def test_pyproject_has_pywin32_platform_guard(self):
        toml_path = os.path.join(PROJECT_ROOT, "pyproject.toml")
        with open(toml_path, "r") as f:
            content = f.read()
        assert "sys_platform == 'win32'" in content

    def test_requirements_txt_has_mcp_ceiling(self):
        """requirements.txt matches pyproject.toml ceiling."""
        req_path = os.path.join(PROJECT_ROOT, "requirements.txt")
        with open(req_path, "r") as f:
            content = f.read()
        assert "mcp>=1.0.0,<1.20" in content

    def test_server_main_is_importable(self):
        """The console_scripts entry point 'server:main' must be importable."""
        # We can't actually import server.py on non-Windows (COM deps),
        # but we can verify the function exists via AST
        import ast
        server_path = os.path.join(PROJECT_ROOT, "server.py")
        with open(server_path, "r") as f:
            tree = ast.parse(f.read())
        main_funcs = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "main"
        ]
        assert len(main_funcs) >= 1, "server.py must define main()"
