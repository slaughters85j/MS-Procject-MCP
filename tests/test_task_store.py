"""
COM Proxy Refresh — TaskStore

Tests for stale-proxy detection, ResolveResult, get_all_tasks,
invalidation/stats and the module singleton in task_store.py.
All tests mock COM — no live MS Project required.
"""

import pytest
from unittest.mock import MagicMock
from src.task_store import (
    TaskStore,
    StoreEvent,
    ResolveResult,
    _is_stale_proxy_error,
    init_store,
    get_store,
)
from tests._task_store_helpers import _make_task, _make_project


# ---------------------------------------------------------------------------
# _is_stale_proxy_error
# ---------------------------------------------------------------------------

class TestStaleProxyDetection:
    def test_detects_rpc_disconnected(self):
        exc = Exception("RPC_E_DISCONNECTED: The object...")
        assert _is_stale_proxy_error(exc) is True

    def test_detects_obj_not_connected(self):
        exc = Exception("CO_E_OBJNOTCONNECTED")
        assert _is_stale_proxy_error(exc) is True

    def test_detects_hex_code_in_message(self):
        exc = Exception("Error 0x800706BA occurred")
        assert _is_stale_proxy_error(exc) is True

    def test_detects_hresult_attribute(self):
        exc = Exception("some error")
        exc.hresult = -2147023174  # 0x800706BA
        assert _is_stale_proxy_error(exc) is True

    def test_normal_exception_not_stale(self):
        exc = Exception("KeyError: 'foo'")
        assert _is_stale_proxy_error(exc) is False

    def test_value_error_not_stale(self):
        exc = ValueError("invalid literal")
        assert _is_stale_proxy_error(exc) is False

    def test_call_rejected(self):
        exc = Exception("Call was rejected by callee")
        assert _is_stale_proxy_error(exc) is True

    def test_realistic_pywintypes_com_error(self):
        """
        Real pywintypes.com_error shape: args is a tuple of
        (hresult, source, description, ...) and .hresult is set.
        We can't import pywintypes on Mac, so build a mock that
        matches the actual exception structure.
        """
        class FakeComError(Exception):
            """Mimics pywintypes.com_error structure."""
            def __init__(self, hresult, source, desc):
                self.hresult = hresult
                self.args = (hresult, source, desc, None)
                super().__init__(f"({hresult}, '{source}', '{desc}')")

        # RPC server unavailable (0x800706BA = -2147023174 signed)
        exc = FakeComError(-2147023174, "DAO.Tasks", "RPC server unavailable")
        assert _is_stale_proxy_error(exc) is True

        # Object disconnected (0x80010108 = -2147417848 signed)
        exc = FakeComError(-2147417848, "DAO.Task", "Object disconnected")
        assert _is_stale_proxy_error(exc) is True

        # A non-stale COM error (e.g., E_INVALIDARG = -2147024809)
        exc = FakeComError(-2147024809, "DAO.Task", "Invalid argument")
        assert _is_stale_proxy_error(exc) is False


# ---------------------------------------------------------------------------
# ResolveResult
# ---------------------------------------------------------------------------

class TestResolveResult:
    def test_to_dict_found(self):
        r = ResolveResult(task=MagicMock(), found=True)
        d = r.to_dict()
        assert d["found"] is True
        assert d["error"] is None
        assert d["retried"] is False

    def test_to_dict_not_found(self):
        r = ResolveResult(error="Not found")
        d = r.to_dict()
        assert d["found"] is False
        assert d["error"] == "Not found"

    def test_to_dict_retried(self):
        r = ResolveResult(task=MagicMock(), found=True, retried=True)
        assert r.to_dict()["retried"] is True


# ---------------------------------------------------------------------------
# TaskStore.get_all_tasks
# ---------------------------------------------------------------------------

class TestGetAllTasks:
    def test_returns_all_non_none(self):
        tasks = [_make_task(uid=i) for i in range(5)]
        tasks.insert(2, None)  # Simulate deleted task gap
        proj = _make_project(tasks=tasks)
        store = TaskStore(lambda: proj)

        result, err = store.get_all_tasks()
        assert len(result) == 5
        assert err is None

    def test_no_project(self):
        store = TaskStore(lambda: None)
        result, err = store.get_all_tasks()
        assert result == []
        assert "No project" in err

    def test_partial_iteration_surfaces_error(self):
        """If iteration fails mid-collection (non-stale), return
        partial results WITH an error message."""
        # Create a project whose Tasks iterator yields 2 then explodes
        proj = MagicMock()
        call_count = [0]
        def fake_iter(_self=None):
            call_count[0] += 1
            yield _make_task(uid=1)
            yield _make_task(uid=2)
            raise Exception("COM iteration bombed")
        proj.Tasks.__iter__ = fake_iter
        store = TaskStore(lambda: proj)

        result, err = store.get_all_tasks()
        assert len(result) == 2  # Got the 2 before the explosion
        assert err is not None
        assert "collected 2" in err

    def test_stale_proxy_retries(self):
        tasks = [_make_task(uid=1)]
        good_proj = _make_project(tasks=tasks)

        call_count = [0]
        def get_proj():
            call_count[0] += 1
            if call_count[0] == 1:
                bad = MagicMock()
                bad.Tasks = MagicMock(
                    __iter__=MagicMock(
                        side_effect=Exception("CO_E_OBJNOTCONNECTED")
                    )
                )
                return bad
            return good_proj

        store = TaskStore(get_proj)
        result, err = store.get_all_tasks()
        assert len(result) == 1
        assert err is None


# ---------------------------------------------------------------------------
# TaskStore.invalidate and get_stats
# ---------------------------------------------------------------------------

class TestInvalidateAndStats:
    def test_invalidation_increments(self):
        proj = _make_project()
        store = TaskStore(lambda: proj)
        assert store.get_stats()["invalidation_count"] == 0

        store.invalidate(StoreEvent.SAVE)
        assert store.get_stats()["invalidation_count"] == 1

        store.invalidate(StoreEvent.SWITCH)
        assert store.get_stats()["invalidation_count"] == 2

    def test_stats_track_resolves(self):
        proj = _make_project(tasks=[_make_task(uid=1)])
        store = TaskStore(lambda: proj)
        store.resolve_task(1)
        store.resolve_resource(1)
        assert store.get_stats()["resolve_count"] == 2

    def test_all_store_events(self):
        """All StoreEvent values should be accepted."""
        store = TaskStore(lambda: _make_project())
        for ev in StoreEvent:
            store.invalidate(ev)
        assert store.get_stats()["invalidation_count"] == len(StoreEvent)


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_init_and_get(self):
        proj = _make_project(tasks=[_make_task(uid=1)])
        store = init_store(lambda: proj)
        assert get_store() is store

    def test_get_before_init_raises(self):
        import src.task_store as mod
        original = mod._store
        mod._store = None
        try:
            with pytest.raises(RuntimeError, match="not initialized"):
                get_store()
        finally:
            mod._store = original
