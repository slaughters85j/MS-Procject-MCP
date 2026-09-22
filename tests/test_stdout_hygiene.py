"""
Verifies no print() calls in server.py or the core tool modules write to stdout.
"""

import os
import sys
import ast
import glob
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SERVER_PY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "server.py",
)
SRC_DIR = os.path.join(os.path.dirname(SERVER_PY), "src")
# server.py plus the modules its core tools moved into.
STDIO_FILES = [SERVER_PY, os.path.join(SRC_DIR, "com_helpers.py"), os.path.join(SRC_DIR, "guards.py")]
STDIO_FILES += sorted(glob.glob(os.path.join(SRC_DIR, "tools", "*.py")))


class TestStderrFix:
    """Verify server.py has no stdout print() calls."""

    @pytest.mark.parametrize("path", STDIO_FILES, ids=os.path.basename)
    def test_no_bare_print_calls(self, path):
        """All print() calls in server.py and the core tool modules must use file=sys.stderr."""
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source, filename=path)
        violations = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Check for print() calls
            func = node.func
            is_print = False
            if isinstance(func, ast.Name) and func.id == "print":
                is_print = True
            elif isinstance(func, ast.Attribute) and func.attr == "print":
                is_print = True

            if not is_print:
                continue

            # Check if file=sys.stderr is specified
            has_stderr = False
            for kw in node.keywords:
                if kw.arg == "file":
                    has_stderr = True
                    break

            if not has_stderr:
                violations.append(node.lineno)

        assert violations == [], (
            f"print() calls without file=sys.stderr found in {path} on lines: {violations}. "
            f"Bare print() corrupts the MCP stdio transport."
        )

    def test_main_function_exists(self):
        """server.py must define a main() function for console_scripts."""
        with open(SERVER_PY, "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source, filename="server.py")
        main_funcs = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        ]
        assert len(main_funcs) >= 1, "server.py must define a main() function"
