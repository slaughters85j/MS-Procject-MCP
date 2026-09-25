"""
Types and stale-proxy detection used by the TaskStore.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


# COM error codes that indicate a stale/disconnected proxy.
# We match on string fragments because importing pywintypes is
# Windows-only and we want the logic testable on Mac.
STALE_PROXY_INDICATORS = (
    "RPC_E_DISCONNECTED",
    "CO_E_OBJNOTCONNECTED",
    "RPC_E_SERVERFAULT",
    "0x800706BA",   # RPC server unavailable
    "0x80010108",   # Object invoked disconnected from clients
    "0x800706BE",   # Remote procedure call failed
    "Call was rejected",
)


class StoreEvent(Enum):
    """Events that invalidate cached COM references."""
    SAVE = "save"
    SWITCH = "switch"
    INSERT = "insert"
    MANUAL = "manual"


def _is_stale_proxy_error(exc: Exception) -> bool:
    """Check if an exception indicates a stale COM proxy."""
    exc_str = str(exc)
    exc_type = type(exc).__name__
    for indicator in STALE_PROXY_INDICATORS:
        if indicator in exc_str or indicator in exc_type:
            return True
    # pywintypes.com_error has an hresult attribute
    hresult = getattr(exc, "hresult", None)
    if hresult is not None:
        # Check known stale-proxy HRESULTs (as signed 32-bit)
        stale_hresults = {
            -2147023174,  # 0x800706BA - RPC server unavailable
            -2147417848,  # 0x80010108 - Object disconnected
            -2147023170,  # 0x800706BE - RPC call failed
        }
        if hresult in stale_hresults:
            return True
    return False


@dataclass
class ResolveResult:
    """Result of a UniqueID resolution attempt."""
    task: Any = None           # COM Task object, or None
    found: bool = False
    error: Optional[str] = None
    retried: bool = False      # True if we retried after stale proxy

    def to_dict(self) -> dict:
        return {
            "found": self.found,
            "error": self.error,
            "retried": self.retried,
        }
