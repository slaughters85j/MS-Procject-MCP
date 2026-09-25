"""
Shared pieces of the kwargs-style live scenario tests: the tool-call helper and a small
pass/fail/skip recorder that prints each check and a final summary.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.dirname(__file__))
from server import mcp  # noqa: E402
from _toolcall import tool_text  # noqa: E402


async def call(tool_name, **kwargs):
    """Call an MCP tool and return parsed JSON."""
    try:
        text = tool_text(await mcp.call_tool(tool_name, kwargs))
        return json.loads(text) if text else {}
    except Exception as e:
        print(f"  [ERROR] {tool_name}: {str(e)[:120]}")
        return {"error": str(e)}


class Checks:
    """Counts and prints the outcome of each scenario check."""

    def __init__(self):
        self.passed = self.failed = self.skipped = 0

    def ok(self, name, cond, detail=""):
        if cond:
            self.passed += 1
            print(f"  PASS  {name}")
        else:
            self.failed += 1
            print(f"  FAIL  {name}  {detail}")

    def skip(self, name, reason=""):
        self.skipped += 1
        print(f"  SKIP  {name}  {reason}")

    def summary(self, title):
        """Print the result line and return True when nothing failed."""
        total = self.passed + self.failed + self.skipped
        print("=" * 60)
        print(f"  {title} results:  {self.passed} passed,  {self.failed} failed,  {self.skipped} skipped  (total {total})")
        print("=" * 60)
        return self.failed == 0
