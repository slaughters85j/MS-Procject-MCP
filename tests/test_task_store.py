"""
COM Proxy Refresh — TaskStore

Tests for task_store.py and store_tools.py.
All tests mock COM — no live MS Project required.
"""

import pytest
from unittest.mock import MagicMock, PropertyMock
from src.task_store import (
    TaskStore,
    StoreEvent,
    ResolveResult,
    _is_stale_proxy_error,
    init_store,
    get_store,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(uid, name="Task", task_id=1):
    """Create a mock COM Task object."""
    t = MagicMock()
    t.UniqueID = uid
    t.Name = name
    t.ID = task_id
    return t


def _make_project(tasks=None, resources=None):
    """Create a mock COM Project with Tasks and Resources."""
    proj = MagicMock()
    proj.Tasks = tasks if tasks is not None else []
    proj.Resources = resources if resources is not None else []
    return proj


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
# TaskStore.resolve_task
# ---------------------------------------------------------------------------

class TestResolveTask:
    def test_finds_task_by_uid(self):
        t1 = _make_task(uid=10, name="Alpha")
        t2 = _make_task(uid=20, name="Beta")
        proj = _make_project(tasks=[t1, t2])
        store = TaskStore(lambda: proj)

        result = store.resolve_task(20)
        assert result.found is True
        assert result.task.Name == "Beta"
        assert result.retried is False

    def test_not_found(self):
        t1 = _make_task(uid=10)
        proj = _make_project(tasks=[t1])
        store = TaskStore(lambda: proj)

        result = store.resolve_task(999)
        assert result.found is False
        assert "not found" in result.error.lower()

    def test_no_project_open(self):
        store = TaskStore(lambda: None)
        result = store.resolve_task(10)
        assert result.found is False
        assert "No project" in result.error

    def test_skips_none_tasks(self):
        """MS Project Tasks collection can have None slots."""
        t1 = _make_task(uid=10)
        proj = _make_project(tasks=[None, t1, None])
        store = TaskStore(lambda: proj)

        result = store.resolve_task(10)
        assert result.found is True

    def test_stale_proxy_retries_once(self):
        """On stale proxy error, should retry with fresh project ref."""
        t1 = _make_task(uid=10, name="Fresh")
        good_proj = _make_project(tasks=[t1])

        call_count = [0]
        def get_proj():
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: return project with stale Tasks
                bad_proj = MagicMock()
                bad_proj.Tasks = MagicMock(
                    __iter__=MagicMock(
                        side_effect=Exception("RPC_E_DISCONNECTED")
                    )
                )
                return bad_proj
            return good_proj

        store = TaskStore(get_proj)
        result = store.resolve_task(10)
        assert result.found is True
        assert result.retried is True
        assert result.task.Name == "Fresh"
        assert store._retry_count == 1

    def test_stale_proxy_fails_after_retry(self):
        """If both attempts hit stale proxy, return error."""
        def get_proj():
            bad = MagicMock()
            bad.Tasks = MagicMock(
                __iter__=MagicMock(
                    side_effect=Exception("RPC_E_DISCONNECTED")
                )
            )
            return bad

        store = TaskStore(get_proj)
        result = store.resolve_task(10)
        assert result.found is False
        assert "COM error" in result.error
        assert result.retried is True

    def test_increments_resolve_count(self):
        proj = _make_project(tasks=[_make_task(uid=1)])
        store = TaskStore(lambda: proj)
        store.resolve_task(1)
        store.resolve_task(1)
        assert store._resolve_count == 2


# ---------------------------------------------------------------------------
# TaskStore.resolve_resource
# ---------------------------------------------------------------------------

class TestResolveResource:
    def test_finds_resource_by_uid(self):
        r1 = _make_task(uid=100, name="Engineer")
        proj = _make_project(resources=[r1])
        store = TaskStore(lambda: proj)

        result = store.resolve_resource(100)
        assert result.found is True
        assert result.task.Name == "Engineer"

    def test_resource_not_found(self):
        proj = _make_project(resources=[_make_task(uid=100)])
        store = TaskStore(lambda: proj)
        result = store.resolve_resource(999)
        assert result.found is False
        assert "not found" in result.error.lower()

    def test_resource_stale_proxy_retry(self):
        r1 = _make_task(uid=100, name="Fresh Resource")
        good_proj = _make_project(resources=[r1])

        call_count = [0]
        def get_proj():
            call_count[0] += 1
            if call_count[0] == 1:
                bad = MagicMock()
                bad.Resources = MagicMock(
                    __iter__=MagicMock(
                        side_effect=Exception("0x80010108")
                    )
                )
                return bad
            return good_proj

        store = TaskStore(get_proj)
        result = store.resolve_resource(100)
        assert result.found is True
        assert result.retried is True


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


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_task_uid_zero(self):
        """UniqueID 0 is valid in MS Project (summary task)."""
        t0 = _make_task(uid=0, name="Project Summary")
        proj = _make_project(tasks=[t0])
        store = TaskStore(lambda: proj)

        result = store.resolve_task(0)
        assert result.found is True
        assert result.task.Name == "Project Summary"

    def test_large_uid(self):
        """UniqueIDs can be large integers."""
        t = _make_task(uid=999999999, name="Big UID")
        proj = _make_project(tasks=[t])
        store = TaskStore(lambda: proj)
        result = store.resolve_task(999999999)
        assert result.found is True

    def test_empty_tasks_collection(self):
        proj = _make_project(tasks=[])
        store = TaskStore(lambda: proj)
        result = store.resolve_task(1)
        assert result.found is False

    def test_individual_task_com_error_skips(self):
        """If reading UniqueID on one task fails (non-stale), skip it."""
        t1 = MagicMock()
        type(t1).UniqueID = PropertyMock(
            side_effect=Exception("Access denied")
        )
        t2 = _make_task(uid=20, name="Good")
        proj = _make_project(tasks=[t1, t2])
        store = TaskStore(lambda: proj)

        result = store.resolve_task(20)
        assert result.found is True
        assert result.task.Name == "Good"

    def test_individual_task_stale_error_triggers_retry(self):
        """If reading UniqueID raises a stale error, retry the whole thing."""
        t_stale = MagicMock()
        type(t_stale).UniqueID = PropertyMock(
            side_effect=Exception("RPC_E_DISCONNECTED")
        )
        t_good = _make_task(uid=10, name="Recovered")
        good_proj = _make_project(tasks=[t_good])

        call_count = [0]
        def get_proj():
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_project(tasks=[t_stale])
            return good_proj

        store = TaskStore(get_proj)
        result = store.resolve_task(10)
        assert result.found is True
        assert result.retried is True

    def test_get_project_fn_called_fresh_each_resolve(self):
        """get_project_fn must be called on every resolve, not cached."""
        call_count = [0]
        def get_proj():
            call_count[0] += 1
            return _make_project(tasks=[_make_task(uid=1)])

        store = TaskStore(get_proj)
        store.resolve_task(1)
        store.resolve_task(1)
        assert call_count[0] == 2
