"""
COM Proxy Refresh — TaskStore resolution

Tests for TaskStore.resolve_task / resolve_resource, including stale-proxy
retry and resolution edge cases.
All tests mock COM — no live MS Project required.
"""

from unittest.mock import MagicMock, PropertyMock
from src.task_store import TaskStore
from tests._task_store_helpers import _make_task, _make_project


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
