"""
Optional safety and infrastructure modules, imported with fallback stubs so the server still
starts, and the core tools keep working, when one of them fails to load. Tool modules import
these names from here rather than from the underlying modules.
"""

import logging

logger = logging.getLogger(__name__)

HARDENING_LOAD_ERRORS = []


def _record_load_error(module_name, exc):
    """Log a hardening module that failed to load and keep the message for health_check."""
    msg = f"{module_name} failed to load ({type(exc).__name__}): {exc}"
    logger.error("Hardening tools unavailable: %s", msg)
    HARDENING_LOAD_ERRORS.append(msg)


# MARK: Path confinement and dry-run mode

try:
    from .safe_path import validate_safe_path, is_confined, get_safe_root
except Exception as _e:
    logger.error("safe_path module failed to load: %s", _e)
    def validate_safe_path(p):  # noqa: E302
        return p
    def is_confined():  # noqa: E302
        return False
    def get_safe_root():  # noqa: E302
        return None

try:
    from .dry_run import is_dry_run, dry_run_response
except Exception as _e:
    logger.error("dry_run module failed to load: %s", _e)
    def is_dry_run():  # noqa: E302
        return False
    def dry_run_response(tool, params):  # noqa: E302
        return "{}"

# MARK: COM retry with geometric backoff

try:
    from .com_retry import com_call, is_com_busy
except Exception as _e:
    logger.error("com_retry module failed to load: %s", _e)
    def com_call(func, **kwargs):  # noqa: E302
        return func()
    def is_com_busy(exc):  # noqa: E302
        return False

# MARK: Response size management

# Callers check _RESPONSE_MGMT before using the response helpers, which are None when it is False.
try:
    from .response import (
        paginate, strip_empty, strip_empty_list, format_response,
        prepare_task_response, prepare_resource_response,
        DEFAULT_PAGE_LIMIT,
    )
    _RESPONSE_MGMT = True
except Exception as _e:
    logger.error("response module failed to load: %s", _e)
    _RESPONSE_MGMT = False
    DEFAULT_PAGE_LIMIT = 200
    paginate = strip_empty = strip_empty_list = format_response = None
    prepare_task_response = prepare_resource_response = None

# MARK: COM session singleton

try:
    from .project_session import get_session
except Exception as e:
    get_session = None
    _record_load_error("src.project_session", e)
