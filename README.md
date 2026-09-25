# MS Project MCP Server

An MCP server for controlling Microsoft Project through COM automation. Python + pywin32 on Windows, with session-managed COM lifecycle, verify-after-write guarantees, and bulk operations with dry-run support.

Built on [FastMCP](https://github.com/jlowin/fastmcp). 100+ tools covering tasks, resources, calendars, baselines, earned value, scheduling analysis, and multi-project workflows.

## Requirements

- **Windows** with Microsoft Project installed (tested on MS Project 16.0)
- **Python 3.10+**
- MS Project must be running (or the server will launch it)

## Installation

```bash
# Clone and install in editable mode
git clone https://github.com/slaughters85j/MS-Project-MCP.git
cd MS-Project-MCP
pip install -e .

# With dev dependencies (pytest, coverage)
pip install -e ".[dev]"
```

This gives you the `msproject-mcp` console script, so you don't need absolute paths in your MCP client config.

## Quick Start

Register the server in your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "msproject": {
      "command": "msproject-mcp"
    }
  }
}
```

Or run directly:

```bash
# Via console script
msproject-mcp

# Or via Python
python server.py
```

The server communicates over stdio. Start MS Project and open a `.mpp` file before issuing tool calls (or use `open_project` / `new_project` to do it from the client).

## Architecture

`server.py` is a thin entry point that creates the FastMCP instance and wires everything together. The core tools live in `src/tools/`, one module per domain (project, tasks, dependencies, resources, calendars, baselines, cost, critical path, and so on), sharing COM helpers from `src/com_helpers.py` and optional safety modules loaded through `src/guards.py`. They are backed by a `src/` package of hardening modules built in work packages WP-1 through WP-8. The hardening modules are optional: if any fail to load (e.g., running on a machine without pywin32), the legacy tools keep working and `health_check` reports what's missing.

### Hardening Work Packages

| WP | Module | Purpose |
|----|--------|---------|
| 1 | `project_session.py` | COM lifecycle singleton. Attach/detach ownership, headless mode, graceful shutdown. Refuses to start if another COM client is already bound. |
| 2 | `project_identity.py` | Canonical file paths and SHA-256 project hash. Every mutating tool accepts an optional `project_id` (path or `hash_id`) and refuses to write if a different project is active. |
| 3 | `verify_write.py` | Re-reads every field after mutation. Returns `{requested, actual, drifted}` so the caller can tell "write succeeded" from "write succeeded but Project recalculated the value." |
| 4 | `calc_policy.py` | `deferred_calc` context manager. Suppresses automatic recalculation during batch writes so 40 field updates don't trigger 40 full recalcs on a 10k-task file. |
| 5 | `task_store.py` | UniqueID-based task resolution on every access. Detects stale COM proxies (from save, switch, or insert) and re-resolves transparently. |
| 6 | `ui_lock.py` | Manages `ScreenUpdating` and `StatusBar` during tool calls. Three modes: invisible (headless), locked (visible but frozen), and open. |
| 7 | `bulk_ops.py` | Dry-run/apply pattern for bulk operations. Idempotent (skips items already matching), per-item verification via WP-3, per-item error reporting. |
| 8 | `tests/integration/` | Fixture generator, pytest conftest with Project session fixture, CI workflow for Windows runners. |

### Safety Features

**Path confinement.** Set `MSPROJECT_SAFE_ROOT` to restrict all file operations (`open_project`, `save_project_as`, `export_csv`, etc.) to a directory tree; paths outside it (including `..` traversal) are refused. Unset = no confinement, so set it for any deployment where the model should not reach the whole filesystem.

**Dry-run mode.** Set `MSPROJECT_DRY_RUN=1` (or `true`/`yes`/`on`) to prevent all mutations server-wide. The gate is applied to every mutating tool in one place (`src/tool_guardrails.py`); they return `"status": "dry-run"` without touching the project, and `bulk_update` is forced to `mode="dry_run"`. Session and view tools (`session_attach`, `switch_project`, `apply_filter`, `open_project`, ...) stay live.

**One guardrail layer for every tool** (`src/tool_guardrails.py`): unknown argument names are rejected (`additionalProperties: false`), the ProjectSession attaches to a running Project on demand (never launching or hiding it), Project's Planning Wizard and alerts are suppressed during writes, and a modal-dialog watchdog cancels any dialog Project raises mid-call instead of hanging the server. Every failure has one shape: `isError: true` with a JSON body `{"error": "...", "error_type": "..."}`.

**Correct COM usage.** Task edits act on COM objects, never on view rows, so a filter or sort cannot redirect a delete or indent to another task (move/copy, which need the clipboard, verify the selection first). Dates are sent as UTC-aware datetimes so pywin32 does not shift them by the local UTC offset; a date-only finish/deadline means the end of that working day. Durations use the project's `HoursPerDay`. Enum values (baselines, calculation mode, progress updates, timescales, link types, custom field IDs) come from the Project type library.

**stderr-only logging.** All diagnostic output goes to stderr. No `print()` calls leak to stdout, which would corrupt the MCP stdio transport.

**ToolAnnotations.** Every tool carries MCP `ToolAnnotations` metadata (`readOnlyHint`, `destructiveHint`, `idempotentHint`) so clients can make safety decisions before calling.

### Production Features

**COM retry with geometric backoff.** Transient `RPC_E_CALL_REJECTED` and `RPC_E_SERVERCALL_RETRYLATER` errors (from recalculation or modal dialogs) are retried with 0.4s/0.8s/1.6s backoff instead of failing immediately.

**Response size management.** Three mechanisms keep responses usable for LLM context windows:

- *Pagination:* Read tools default to 200 items per page with `offset`/`limit` parameters. Use `limit=-1` for everything at once.
- *Field stripping:* Empty, null, false, and zero-valued fields are omitted from task/resource dicts. Identity fields (`unique_id`, `name`) and measurement zeros (`percent_complete`, `duration_days`) are always kept.
- *Adaptive formatting:* Responses over 4 KB use compact JSON; smaller responses stay indented for readability.

**Schema size reduction.** Pydantic's auto-generated `"title"` fields are stripped from all tool schemas at import time, saving ~2,300 tokens of context per session.

**Server instructions and tool guide.** The server registers `instructions` with FastMCP so LLM clients receive batching rules and a single-to-bulk cross-reference map at init. The `get_tool_guide()` meta-tool returns the full categorized tool inventory on demand.

**MCP Registry manifest.** A `server.json` file is included for discoverability in the MCP Registry ecosystem.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MSPROJECT_SAFE_ROOT` | *(unset = no confinement)* | Directory tree where file operations are allowed. Paths outside this root are rejected. Recommended for every deployment. |
| `MSPROJECT_DRY_RUN` | `0` | Set to `1` to prevent all mutations server-wide. Every mutating tool returns a dry-run preview. |
| `MSPROJECT_AUTOSAVE` | `1` | Save the project after every mutating tool call. Set to `0` to keep changes unsaved (and keep Project's undo history, which every save clears). Untitled projects are never auto-saved. |

## Tool Inventory

The server exposes 100+ tools organized by domain. Use `get_tool_guide()` for the full categorized list with descriptions. Here's the summary:

| Category | Tools | Examples |
|----------|-------|---------|
| Project Management | 7 | `open_project`, `save_project`, `get_project_info` |
| Task Queries | 9 | `get_tasks`, `get_critical_path`, `search_tasks`, `get_wbs_structure` |
| Task Mutations | 12 | `update_task`, `add_task`, `bulk_add_tasks`, `add_recurring_task` |
| Dependencies | 4 | `add_predecessor`, `bulk_add_predecessors`, `get_task_dependencies` |
| Resources | 7 | `get_resources`, `add_resource`, `assign_resource` |
| Resource Assignments | 3 | `bulk_assign_resources`, `get_resource_workload` |
| Custom Fields | 3 | `rename_custom_fields`, `update_custom_fields` |
| Import/Export | 6 | `export_csv`, `snapshot_to_json`, `snapshot_diff` |
| Calendars | 8 | `get_calendars`, `create_calendar`, `set_calendar_exception` |
| Scheduling & Analysis | 12 | `validate_schedule`, `what_if_delay`, `get_critical_path_sequence` |
| Baselines & Earned Value | 4 | `save_baseline`, `compare_baselines`, `get_earned_value` |
| Cost & Work | 4 | `get_cost_summary`, `get_variance_report` |
| Progress Tracking | 4 | `update_project`, `reschedule_incomplete_work` |
| Advanced Operations | 8 | `dry_run_bulk_update`, `copy_task_structure`, `cross_project_link` |
| Multi-Project | 3 | `list_projects`, `switch_project` |
| Filtering & Grouping | 2 | `filter_tasks`, `group_tasks_by` |
| Session & Identity (WP) | ~10 | `session_info`, `health_check`, `calculate_project` |
| Connectivity | 1 | `health_check` |

Every task query returns a rich dict with 35+ fields including actual start/finish, remaining duration, total/free slack, deadline, priority, constraint type, scheduling mode, and hyperlinks. See the tool schemas or `get_tool_guide()` output for full field documentation.

## Development

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Unit tests (no MS Project required)
pytest tests/ -v

# Integration tests (Windows with MS Project installed; close Project first)
python tests/fixtures/generate_fixtures.py
pytest tests/integration/ -v
```

Unit tests in `tests/` mock COM and mpxj, so they run on any platform. `tests/integration/` holds the live tests: per-module COM tests for the hardening modules, plus tool-level scenario tests (`*_live.py`) that drive the MCP tools end to end against a real MS Project. They skip automatically when MS Project is not available, and `tests/fixtures/generate_fixtures.py` builds the fictional `.mpp` fixtures they use. The integration tests start their own hidden Project instance and quit it afterwards, so they refuse to run (skip) while you have Project open; they never attach to or close your session.

### Branch Structure

- `main` -- stable releases
- `dev` -- active development, hardening work packages and fork integrations

### CI

The GitHub Actions workflow runs on Windows runners with MS Project installed. See `docs/ci-setup.md` for runner requirements and Project licensing notes.

## Known Limitations

- **COM proxy staleness:** Switching projects invalidates existing COM references. The WP-5 TaskStore handles this automatically, but legacy tools may need a `switch_project` call first.
- **Undo stack:** saving clears MS Project's undo history, so with autosave on (the default) `undo_last` has nothing to undo after a tool write and says so. Run with `MSPROJECT_AUTOSAVE=0` to use it.
- **Moving/copying tasks:** Project has no COM move/copy API, so `move_task` and `copy_task_structure` use cut/copy/paste, which assigns new UniqueIDs (returned as `uid_map`; links are kept). `move_task` keeps the task's outline level unless `keep_outline_level=false`.
- **Baselines for specific tasks:** pass `unique_ids` to `save_baseline`/`clear_baseline`; `all_tasks=false` alone is refused rather than acting on whatever is selected in Project.
- **File locking:** Only one process can hold the COM connection. Don't open Project's GUI dialogs while the server is active (or use headless mode via WP-1).
- **Recurring tasks:** MS Project's `RecurringTaskInsert` is dialog-only in COM. The `add_recurring_task` tool simulates recurrence by creating individual occurrences under a summary task.
- **Timephased data:** `get_timephased_data` can be slow on large date ranges. Keep queries to weeks or months, not years.

## Credits

Forked from [elsahafy/MS-Procject-MCP](https://github.com/elsahafy/MS-Procject-MCP). The hardening architecture (WP-1 through WP-8) was built on top of that foundation. Several production features were adapted from two other forks:

- [devGPL/MS-Procject-MCP](https://github.com/devGPL/MS-Procject-MCP): pyproject.toml packaging, COM retry with backoff, response size management (pagination, field stripping, adaptive formatting), schema size reduction, MCP Registry manifest, improved error diagnostics.
- [4nswer/Project_MCP](https://github.com/4nswer/Project_MCP): `MSPROJECT_SAFE_ROOT` path confinement, `MSPROJECT_DRY_RUN` mode, ToolAnnotations on all tools, server instructions and tool guide.

See `docs/fork-comparison.md` for the full analysis and `docs/work-packages.md` for the hardening design.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, conventions, and how to submit changes.

## License

MIT. See [LICENSE](LICENSE).
