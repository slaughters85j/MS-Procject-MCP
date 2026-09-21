"""
Shared fakes for mock-based tests. No live MS Project or pywin32 required.
"""


class FakeComError(Exception):
    """Shape of pywintypes.com_error: an hresult attribute and an args tuple."""

    def __init__(self, hresult=-2147418111, text="Call was rejected by callee."):
        super().__init__(hresult, text, None, None)
        self.hresult = hresult


class FakeApp:
    """
    Stand-in for MSProject.Application with Visible, ScreenUpdating, and
    StatusBar. Add "Name.get" or "Name.set" to .fail to make that access
    raise FakeComError. Every successful write is recorded in .writes.
    """

    def __init__(self, visible=True, screen_updating=True):
        self._values = {
            "Visible": visible,
            "ScreenUpdating": screen_updating,
            "StatusBar": False,
        }
        self.fail = set()
        self.writes = []

    def __getattr__(self, name):
        values = self.__dict__.get("_values", {})
        if name not in values:
            raise AttributeError(name)
        if f"{name}.get" in self.fail:
            raise FakeComError()
        return values[name]

    def __setattr__(self, name, value):
        if name in ("_values", "fail", "writes"):
            object.__setattr__(self, name, value)
            return
        if f"{name}.set" in self.fail:
            raise FakeComError()
        self.writes.append((name, value))
        self._values[name] = value


class FakeMCP:
    """Captures functions registered with @mcp.tool()."""

    def __init__(self):
        self.tools = {}

    def tool(self):
        def register(fn):
            self.tools[fn.__name__] = fn
            return fn
        return register
