"""
Sprint 2 tests: COM Retry with Geometric Backoff (src/com_retry.py)

Tests the retry logic, backoff timing, and correct propagation of
non-busy errors. Uses the FakeComError from tests/fakes.py.
"""

import time
import pytest
from tests.fakes import FakeComError
from src.com_retry import (
    com_call,
    com_retry,
    is_com_busy,
    _extract_hresult,
    _COM_BUSY_HRESULTS,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_INITIAL_DELAY,
)


# ---------------------------------------------------------------------------
# _extract_hresult
# ---------------------------------------------------------------------------

class TestExtractHresult:
    def test_from_hresult_attr(self):
        exc = FakeComError(hresult=-2147418111)
        assert _extract_hresult(exc) == -2147418111

    def test_from_args_tuple(self):
        exc = Exception(-2147417846, "retry later", None, None)
        assert _extract_hresult(exc) == -2147417846

    def test_no_hresult(self):
        exc = ValueError("unrelated")
        assert _extract_hresult(exc) is None


# ---------------------------------------------------------------------------
# is_com_busy
# ---------------------------------------------------------------------------

class TestIsComBusy:
    def test_call_rejected(self):
        assert is_com_busy(FakeComError(hresult=-2147418111))

    def test_retry_later(self):
        assert is_com_busy(FakeComError(hresult=-2147417846))

    def test_unrelated_error(self):
        assert not is_com_busy(ValueError("nope"))

    def test_different_hresult(self):
        assert not is_com_busy(FakeComError(hresult=-2147024891))


# ---------------------------------------------------------------------------
# com_call
# ---------------------------------------------------------------------------

class TestComCall:
    def test_success_first_try(self):
        assert com_call(lambda: 42) == 42

    def test_retries_then_succeeds(self):
        """Busy twice, then succeeds on third attempt."""
        calls = {"count": 0}

        def flaky():
            calls["count"] += 1
            if calls["count"] < 3:
                raise FakeComError(hresult=-2147418111)
            return "ok"

        result = com_call(flaky, initial_delay=0.01)
        assert result == "ok"
        assert calls["count"] == 3

    def test_exhausts_retries(self):
        """All attempts busy -> raises the last busy error."""
        def always_busy():
            raise FakeComError(hresult=-2147418111)

        with pytest.raises(FakeComError):
            com_call(always_busy, max_attempts=3, initial_delay=0.01)

    def test_non_busy_propagates_immediately(self):
        """Non-busy error propagates on first attempt, no retry."""
        calls = {"count": 0}

        def real_error():
            calls["count"] += 1
            raise ValueError("real failure")

        with pytest.raises(ValueError, match="real failure"):
            com_call(real_error, max_attempts=4, initial_delay=0.01)
        assert calls["count"] == 1  # No retry

    def test_geometric_backoff_timing(self):
        """Verify backoff is geometric: ~0.01, ~0.02, ~0.04."""
        calls = {"count": 0}

        def always_busy():
            calls["count"] += 1
            raise FakeComError(hresult=-2147418111)

        t0 = time.monotonic()
        with pytest.raises(FakeComError):
            com_call(always_busy, max_attempts=4, initial_delay=0.01)
        elapsed = time.monotonic() - t0
        # 3 waits: 0.01 + 0.02 + 0.04 = 0.07s. Allow generous margin.
        assert elapsed >= 0.05
        assert elapsed < 1.0  # Should be well under 1s

    def test_retry_later_hresult(self):
        """RPC_E_SERVERCALL_RETRYLATER is also retried."""
        calls = {"count": 0}

        def retry_later_then_ok():
            calls["count"] += 1
            if calls["count"] == 1:
                raise FakeComError(hresult=-2147417846)
            return "recovered"

        assert com_call(retry_later_then_ok, initial_delay=0.01) == "recovered"


# ---------------------------------------------------------------------------
# com_retry decorator
# ---------------------------------------------------------------------------

class TestComRetryDecorator:
    def test_decorator_success(self):
        @com_retry(initial_delay=0.01)
        def add(a, b):
            return a + b

        assert add(3, 4) == 7

    def test_decorator_retries_busy(self):
        calls = {"count": 0}

        @com_retry(initial_delay=0.01)
        def flaky_fn():
            calls["count"] += 1
            if calls["count"] < 2:
                raise FakeComError(hresult=-2147418111)
            return "done"

        assert flaky_fn() == "done"
        assert calls["count"] == 2

    def test_decorator_preserves_name(self):
        @com_retry(label="my_func")
        def my_func():
            pass

        assert my_func.__name__ == "my_func"

    def test_decorator_with_kwargs(self):
        @com_retry(initial_delay=0.01, label="kw_test")
        def greet(name="world"):
            return f"hello {name}"

        assert greet(name="John") == "hello John"
