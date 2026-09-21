"""
Sprint 2, Item #7: COM Retry with Geometric Backoff

Handles transient COM "busy" errors that occur when MS Project is
recalculating, showing a modal dialog, or settling after a large operation.

Two HRESULT codes signal "busy, ask again":
  RPC_E_CALL_REJECTED       0x80010001  (-2147418111)
  RPC_E_SERVERCALL_RETRYLATER  0x8001010A  (-2147417846)

These are NOT "MS Project crashed" errors. They are transient refusals
from the OLE message filter. Retrying after a short delay resolves them.

Adapted from devGPL fork's _com_retry(), rewritten to integrate with
our WP-1 ProjectSession architecture rather than their flat module layout.
"""

import functools
import logging
import time
from typing import TypeVar, Callable, Any

logger = logging.getLogger(__name__)

# COM HRESULT codes that mean "busy, try again" (signed 32-bit).
_COM_BUSY_HRESULTS = frozenset({
    -2147418111,  # RPC_E_CALL_REJECTED      (0x80010001)
    -2147417846,  # RPC_E_SERVERCALL_RETRYLATER (0x8001010A)
})

# Default retry parameters: 4 attempts, geometric backoff starting at 0.4s.
# Total wait before giving up: 0.4 + 0.8 + 1.6 = 2.8s.
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_INITIAL_DELAY = 0.4


def _extract_hresult(exc: Exception) -> int | None:
    """Extract the HRESULT from a COM exception.

    pywintypes.com_error stores it as .hresult.
    Some wrappers put it in args[0] instead.
    Returns None if no HRESULT can be found.
    """
    hresult = getattr(exc, "hresult", None)
    if hresult is not None:
        return hresult
    args = getattr(exc, "args", ())
    if args and isinstance(args[0], int):
        return args[0]
    return None


def is_com_busy(exc: Exception) -> bool:
    """Return True if the exception is a transient COM busy error."""
    hresult = _extract_hresult(exc)
    return hresult in _COM_BUSY_HRESULTS


def com_call(
    func: Callable[[], Any],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    label: str = "",
) -> Any:
    """Execute a COM call with retry on transient busy errors.

    Args:
        func: Zero-arg callable that performs the COM operation.
        max_attempts: Total attempts before giving up.
        initial_delay: Seconds to wait after first failure (doubles each retry).
        label: Optional label for log messages (e.g. "GetActiveObject").

    Returns:
        Whatever func() returns on success.

    Raises:
        The last COM busy exception if all retries exhausted.
        Any non-busy exception immediately (no retry).
    """
    last_exc = None
    tag = f" [{label}]" if label else ""

    for attempt in range(max_attempts):
        try:
            return func()
        except Exception as exc:
            if not is_com_busy(exc):
                raise  # Not a busy error — propagate immediately.
            last_exc = exc
            if attempt < max_attempts - 1:
                delay = initial_delay * (2 ** attempt)
                logger.debug(
                    "COM busy%s (attempt %d/%d, HRESULT %s) — retrying in %.1fs",
                    tag, attempt + 1, max_attempts,
                    _extract_hresult(exc), delay,
                )
                time.sleep(delay)
            else:
                logger.warning(
                    "COM busy%s — all %d attempts exhausted (HRESULT %s)",
                    tag, max_attempts, _extract_hresult(exc),
                )
    raise last_exc  # type: ignore[misc]


def com_retry(
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    initial_delay: float = DEFAULT_INITIAL_DELAY,
    label: str = "",
):
    """Decorator form of com_call for wrapping entire functions.

    Usage:
        @com_retry(label="get_tasks")
        def get_tasks():
            return app.ActiveProject.Tasks

    The decorated function retries on COM busy errors with geometric backoff.
    Non-busy exceptions propagate immediately.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return com_call(
                lambda: func(*args, **kwargs),
                max_attempts=max_attempts,
                initial_delay=initial_delay,
                label=label or func.__name__,
            )
        return wrapper
    return decorator
