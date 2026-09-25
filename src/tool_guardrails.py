"""
Guardrails applied to every registered tool, after registration and annotation.

Each tool's run() is wrapped so that, uniformly across all tools:
- Unknown argument names are rejected (the schema says additionalProperties: false).
- The ProjectSession is attached to a running Project on demand, so the hardening tools
  work without an explicit session_attach.
- MSPROJECT_DRY_RUN blocks every mutating tool (bulk_update is forced to mode="dry_run").
- Mutating tools accept an optional project_id and refuse to run against another project.
- Mutating tools run with Planning Wizard and alerts suppressed, under a modal-dialog watchdog.
- Failures have one shape: isError=true with a JSON body {"error": "...", "error_type": "..."}.
"""

import json
import logging

logger = logging.getLogger(__name__)

# Mutating tools that stay live under MSPROJECT_DRY_RUN: they change session or view state,
# never schedule data.
DRY_RUN_EXEMPT = {
    "session_attach", "session_detach", "set_ui_mode", "invalidate_store",
    "switch_project", "switch_project_confirmed", "apply_filter", "open_project",
}
# Tools that must not trigger an auto-attach.
NO_AUTO_ATTACH = {"session_attach", "session_detach", "session_info", "health_check", "get_tool_guide"}
# Session/view tools that never touch schedule data: no UI suppression (session_detach releases
# the COM proxy mid-call, so a restore afterwards would fail and leave the wizard switched off).
NO_QUIET_UI = {"session_attach", "session_detach", "set_ui_mode", "invalidate_store"}
# Tools whose "error" key is part of a normal answer rather than a failure.
ERROR_IS_RESULT = {"validate_project"}

PROJECT_ID_SCHEMA = {
    "type": "string",
    "description": ("Optional guard: file path or hash_id (see get_project_identity) of the project "
                    "this write is meant for. The call is refused if a different project is active."),
}


def _error_result(message, error_type="error", **extra):
    from mcp.types import CallToolResult, TextContent
    payload = {"error": message, "error_type": error_type, **extra}
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload, indent=2))], isError=True)


def _describe_exception(exc):
    """Map an exception to (message, error_type), unwrapping COM and validation errors."""
    try:
        import pywintypes
        if isinstance(exc, pywintypes.com_error):
            info = exc.args[2] if len(exc.args) > 2 else None
            detail = info[2] if info and info[2] else (exc.args[1] if len(exc.args) > 1 else str(exc))
            return f"MS Project rejected the operation: {str(detail).strip()}", "com_error"
    except ImportError:
        pass
    try:
        from pydantic import ValidationError
        if isinstance(exc, ValidationError):
            parts = [f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}" for e in exc.errors()]
            return "Invalid arguments: " + "; ".join(parts), "invalid_arguments"
    except ImportError:
        pass
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return str(exc), "invalid_input"
    return f"{type(exc).__name__}: {exc}", type(exc).__name__


def _error_payload(result, tool_name):
    """Return an error dict if the tool's own result reports a failure, else None."""
    data = result
    if isinstance(result, str):
        text = result.strip()
        if not text.startswith("{"):
            return None
        try:
            data = json.loads(text)
        except ValueError:
            return None
    if not isinstance(data, dict) or tool_name in ERROR_IS_RESULT or not data.get("error"):
        return None
    if data["error"] is True:  # mpxj shape: {"error": true, "error_type", "message"}
        data = {**data, "error": data.get("message", "error")}
        data.pop("message", None)
    return data


def _app_or_none():
    try:
        from .com_helpers import _find_app
        return _find_app()
    except Exception:
        return None


class _QuietUI:
    """Suppress Project alerts and Planning Wizard prompts for one call, restoring the wizard after."""

    def __init__(self, app):
        self.app = app
        self.wizard = None

    def __enter__(self):
        if self.app is None:
            return self
        try:
            self.app.DisplayAlerts = False
            self.wizard = self.app.DisplayPlanningWizard
            self.app.DisplayPlanningWizard = False
        except Exception as e:
            logger.debug("Could not suppress Project UI: %s", e)
        return self

    def __exit__(self, *exc):
        if self.app is not None and self.wizard is not None:
            try:
                self.app.DisplayPlanningWizard = self.wizard
            except Exception:
                pass
        return False


def _forbid_extra_args(tool):
    model = tool.fn_metadata.arg_model
    strict = type(model.__name__, (model,), {
        "model_config": {**model.model_config, "extra": "forbid"},
        "__module__": model.__module__,
    })
    tool.fn_metadata.arg_model = strict
    tool.parameters["additionalProperties"] = False


def _wrap(tool, mutating):
    from .guards import is_dry_run, dry_run_response, get_session
    from .modal_guard import ModalWatchdog
    original_run = tool.run
    name = tool.name

    async def run(arguments, context=None, convert_result=False):
        arguments = dict(arguments or {})
        project_id = arguments.pop("project_id", None) if mutating else None
        try:
            if get_session is not None and name not in NO_AUTO_ATTACH and not name.startswith("mpxj_"):
                get_session().ensure_attached()
            app = _app_or_none() if mutating and name not in NO_QUIET_UI else None
            if project_id:
                from .project_identity import validate_project_target
                validate_project_target(app or _app_or_none(), project_id)
            if mutating and is_dry_run() and name not in DRY_RUN_EXEMPT:
                if name == "bulk_update":
                    arguments["mode"] = "dry_run"
                else:
                    tool.fn_metadata.arg_model.model_validate(arguments)
                    preview = dry_run_response(name, arguments)
                    return tool.fn_metadata.convert_result(preview) if convert_result else preview
            with _QuietUI(app), ModalWatchdog() as watchdog:
                try:
                    result = await original_run(arguments, context=context, convert_result=False)
                except Exception as e:
                    cause = e.__cause__ or e
                    message, error_type = _describe_exception(cause)
                    if watchdog.dismissed:
                        return _error_result(message, "blocked_by_dialog", dialogs_cancelled=watchdog.dismissed)
                    return _error_result(message, error_type)
            if watchdog.dismissed:
                return _error_result("MS Project opened a dialog during this call; it was cancelled.",
                                     "blocked_by_dialog", dialogs_cancelled=watchdog.dismissed)
        except Exception as e:
            message, error_type = _describe_exception(e)
            return _error_result(message, error_type)
        payload = _error_payload(result, name)
        if payload is not None:
            return _error_result(payload.pop("error"), payload.pop("error_type", "error"), **payload)
        return tool.fn_metadata.convert_result(result) if convert_result else result

    object.__setattr__(tool, "run", run)


def apply_guardrails(server):
    """Wrap every registered tool. Returns the number of tools wrapped."""
    from .annotations import TOOL_ANNOTATIONS
    try:
        tools = list(server._tool_manager._tools.values())
    except AttributeError:
        logger.warning("Could not access FastMCP tool manager; skipping guardrails.")
        return 0
    count = 0
    for tool in tools:
        mutating = not TOOL_ANNOTATIONS.get(tool.name, {}).get("readOnlyHint", False)
        _forbid_extra_args(tool)
        if mutating:
            tool.parameters.setdefault("properties", {})["project_id"] = dict(PROJECT_ID_SCHEMA)
        _wrap(tool, mutating)
        count += 1
    return count
