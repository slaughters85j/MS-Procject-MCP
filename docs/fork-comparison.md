# Fork Comparison: Steal List

**Date:** 2026-09-21
**Our branch:** `dev` at `/Users/system-backup/clawd/dev_local/MS-Procject-MCP`
**Forks analyzed:**
- **devGPL/MS-Procject-MCP** (67 commits ahead) -- v0.7.2, modularized, PyPI-published
- **4nswer/Project_MCP** (8 commits ahead) -- safety-hardened, single-file, discoverability pass

---

## Our Architecture Summary (WP-1 through WP-8)

| WP | Module | What it does |
|----|--------|-------------|
| 1 | `project_session.py` | COM lifecycle singleton, attach/detach, headless mode |
| 2 | `project_identity.py` | Canonical paths, SHA-256 project hash |
| 3 | `verify_write.py` | Re-read fields post-mutation, drift classification |
| 4 | `calc_policy.py` | `deferred_calc` context manager, auto/manual modes |
| 5 | `task_store.py` | UniqueID resolution, stale proxy detection |
| 6 | `ui_lock.py` | ScreenUpdating, StatusBar, invisible/locked/open modes |
| 7 | `bulk_ops.py` / `bulk_tools.py` | Dry-run/apply, idempotent, per-item verify |
| 8 | `tests/integration/` | Fixture generator, conftest, CI workflow |

**Layout:** `src/` package with per-WP modules + tool registration files (*_tools.py). Server.py is entry point with `WP_TOOL_MODULES` dynamic import pattern. ~5300 lines in server.py (legacy tools) + WP modules in src/. Tests split into unit (test_wp*.py) and integration (tests/integration/).

---

## DIRECTLY PORTABLE

Items we can adopt with minimal conflict against our WP architecture.

### 1. pyproject.toml + Console Script Entry Point
**Fork:** devGPL
**Priority:** P1 | **Effort:** S

They have a complete `pyproject.toml` with:
- `setuptools` build backend
- Dependency declarations with version pins and platform markers (`pywin32>=306; sys_platform == 'win32'`)
- `mcp>=1.16,<1.20` ceiling (avoids `pyjwt[crypto]` -> `cryptography` ARM64 build failure)
- Console script: `msproject-mcp = "server:main"` -- eliminates absolute paths in client configs
- PyPI classifiers, project URLs, optional `[fast]` extra for mpxj/jpype

**What to steal:** The whole pyproject.toml structure. We have only `requirements.txt`. The mcp version ceiling is well-reasoned (documented ARM64 issue). The console script entry point is a significant UX improvement for registration.

**Conflicts:** Our code lives in `src/` as a package; their flat modules use `py-modules`. We'd need `[tool.setuptools.packages]` instead. Minor adaptation.

### 2. server.json for MCP Registry
**Fork:** devGPL
**Priority:** P2 | **Effort:** S

Standard MCP Registry manifest:
```json
{
  "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.github.devGPL/msproject-mcp",
  "packages": [{ "registryType": "pypi", "identifier": "msproject-mcp" }]
}
```

**What to steal:** The file verbatim (change identity fields). Makes us discoverable in the MCP Registry ecosystem.

**Conflicts:** None.

### 3. MSPROJECT_SAFE_ROOT Path Confinement
**Fork:** 4nswer
**Priority:** P1 | **Effort:** S

Environment variable read once at startup. Every file-taking tool (`open_project`, `save_project_as`, `export_csv`, `snapshot_to_json`, `insert_subproject`) routes paths through `_resolve_safe_path()`. **Unset = all file ops refused** (fail-closed).

**What to steal:** The `_resolve_safe_path()` pattern and env var convention. Our server.py's `open_project`, `save_project_as`, `import_xml`, `export_xml`, `export_csv` all take raw file paths with zero validation today. This is a real security gap for LLM-driven file access.

**Conflicts:** None. Purely additive guard on existing file-path parameters.

### 4. MSPROJECT_DRY_RUN Mode
**Fork:** 4nswer
**Priority:** P1 | **Effort:** S

Env var `MSPROJECT_DRY_RUN=1` makes `_save()` skip persistence and irreversible deletions short-circuit, returning `"status": "dry-run"` preview.

**What to steal:** The concept, but our WP-7 already has a richer dry-run/apply pattern with per-item verify. Best approach: wire the env var to set a server-wide default that WP-7's `mode="dry_run"` already supports. For non-WP tools (legacy server.py tools), add the `_save()` guard pattern.

**Conflicts:** Overlaps with WP-7's dry-run. Our design is better (per-operation choice vs. global kill switch), but the env var as a deployment-level safety net is complementary.

### 5. stderr-Only Logging
**Fork:** Both (devGPL fixed it, 4nswer documented it)
**Priority:** P1 | **Effort:** S

devGPL's changelog documents the bug: startup messages written to **stdout** corrupt the MCP stdio transport. Their fix: `print("...", file=sys.stderr)`.

**What to check:** Our server.py line 17 creates the logger but we need to verify no `print()` calls leak to stdout. The devGPL fix is `print(..., file=sys.stderr)` for the two startup banner lines.

**Conflicts:** None.

### 6. Tool Schema Size Reduction (`limpar_titulos_do_schema`)
**Fork:** devGPL
**Priority:** P2 | **Effort:** S

Strips pydantic's auto-generated `"title"` from every schema property. Measured: 8.0 KB of 50.7 KB tool definitions (2,300 tokens) removed. Runs at import time so all consumers see the same definitions.

**What to steal:** The `limpar_titulos_do_schema()` function from msp_core.py. Drop-in addition to our server startup.

**Conflicts:** None. Operates on FastMCP internals (`_tool_manager._tools`) with graceful fallback.

### 7. COM Retry with Backoff (`_com_retry`)
**Fork:** devGPL
**Priority:** P2 | **Effort:** S

Wraps COM calls to handle `RPC_E_CALL_REJECTED` and `RPC_E_SERVERCALL_RETRYLATER` with geometric backoff (0.4s, 0.8s, 1.6s). These are transient "busy" errors from recalculation/modal dialogs.

**What to steal:** The `_com_retry()` function. Our `get_app()` and all COM-touching code currently has no retry logic. This is a real reliability improvement.

**Conflicts:** Our WP-1 `ProjectSession.attach()` manages the COM lifecycle differently but doesn't handle transient busy errors either. Complementary.

### 8. Improved Error Message in get_app()
**Fork:** devGPL
**Priority:** P2 | **Effort:** S

Their `get_app()` error message explains the three failure modes: (1) MS Project not running, (2) elevated shell hiding ROT, (3) wrong logon session (SSH). Our message just says "MS Project is not running."

**What to steal:** The diagnostic error text. Direct replacement for our RuntimeError strings.

**Conflicts:** Our WP-1 session's `_find_app()` falls back through session -> GetActiveObject. The error message improvement applies to both paths.

### 9. Response Size Management
**Fork:** devGPL
**Priority:** P2 | **Effort:** M

Three-part system:
- **Pagination:** Default 200-item cap with `recortar()` that adds `truncated` flag and instructions
- **Field stripping:** `enxugar()` drops empty/zero/false fields (57% of values in real schedules)
- **Adaptive formatting:** `responder()` uses compact JSON above 4KB, indented below

Measured: `get_tasks` went from 8.07 MB to ~82 KB on 8,243-task schedule.

**What to steal:** All three functions (`recortar`, `enxugar`, `responder`). Our tools return `json.dumps(payload, indent=2)` everywhere, which means multi-MB responses on real schedules. This is a critical fix for LLM context window consumption.

**Conflicts:** Changes the response shape (missing keys = empty). All consumers must handle `.get()` instead of `[]`. Breaking change for existing clients.

---

## REQUIRES ADAPTATION

Good ideas that conflict with our WP architecture and need rework.

### 10. Modular File Split (msp_*.py)
**Fork:** devGPL
**Priority:** P3 | **Effort:** L

Split from single 5,206-line server.py into 10 flat modules:
- `msp_core.py` -- COM boundary, shared helpers, FastMCP instance
- `msp_tasks_read.py`, `msp_tasks_write.py` -- read/write task tools
- `msp_dependencies.py`, `msp_resources.py`, `msp_calendars.py`
- `msp_schedule.py` -- critical path, slack, leveling
- `msp_baselines_costs.py`, `msp_customfields.py`, `msp_projects.py`
- `msp_fast.py` -- mpxj fast-read path

**Assessment:** Their split is by domain (calendars, resources, schedule). Our split is by concern (session lifecycle, identity, verification, calc policy, task store, UI lock, bulk ops). These are orthogonal architectures. Their domain split is cleaner for a flat tool registry; our concern split is better for the hardening guarantees each WP provides.

**What to take:** The *idea* of msp_core.py as the single COM boundary (all `import win32com` inside function bodies, deferred). We partially do this but our server.py still has inline COM helpers. A consolidation into our src/ structure makes sense as a future WP.

**Conflicts:** Major. Their flat `py-modules` layout vs. our `src/` package. Their import-side-effect tool registration vs. our `WP_TOOL_MODULES` explicit loading. Adopting their split wholesale would discard WP-1 through WP-6. **Do not adopt directly.**

### 11. Fast Read Path (mpxj/jpype)
**Fork:** devGPL
**Priority:** P2 | **Effort:** L

Parses `.mpp` from disk instead of walking COM. Measured: 1.6s vs. 30-48s on 8,429-task schedule. Per-call decision with `source` block in every response. Falls back to COM when:
- mpxj/jpype not installed (no ARM64 wheel)
- Project never saved / file not on disk
- Parse failure (bug, not config -- flagged loudly)

Includes `VistaCOM` abstraction: lazy COM property reader that caches per-field, so a filter reading 3 fields pays for 3 reads, not 35.

**What to steal:** The concept and the backend-abstraction pattern. But not the code directly -- it would need to respect our WP-5 TaskStore (UniqueID resolution) and WP-3 verify-after-write (which reads back from COM, not from file).

**Conflicts:**
- WP-3 verify-after-write reads the *live* COM state. The fast path reads the *saved file*. These are fundamentally different data sources. Verify must stay on COM.
- WP-5 TaskStore maintains a UniqueID -> proxy map. The fast path bypasses this entirely.
- Our `deferred_calc` (WP-4) and `UILock` (WP-6) are COM operations that don't apply to file reads.

**Recommendation:** Implement as a WP-9 with clear boundaries: fast path for READ-ONLY tools only, COM path for all mutations and verification. The `varredura()` decision function is well-designed.

### 12. ToolAnnotations on All Tools
**Fork:** 4nswer
**Priority:** P2 | **Effort:** M

MCP `ToolAnnotations(title, readOnly, destructive, idempotentHint)` on all 101 tools. Tally: 40 read-only, 13 destructive, 26 idempotent, 22 plain-mutating.

**What to steal:** The annotation pattern, but we need to classify our tools independently (our WP tools have different mutation semantics -- e.g., WP-7 bulk ops are idempotent by design, WP-3 verify-after-write adds a read-back after every mutation).

**Conflicts:** Requires auditing all ~99+ tools. The categories may differ from 4nswer's since our WP tools change the mutation behavior.

### 13. Server Instructions + Tool Guide
**Fork:** 4nswer
**Priority:** P2 | **Effort:** S

`FastMCP("MS Project", instructions=SERVER_INSTRUCTIONS)` with:
- Batching rule: "prefer bulk_* over looping single tools"
- Single-to-bulk cross-reference map sent to client at init
- `get_tool_guide()` meta-tool returning categorized tool inventory

**What to steal:** The `instructions` parameter and the cross-reference pattern. Directly applicable -- our `server.py` already groups tools but doesn't tell the LLM client about groupings.

**Conflicts:** Our tool categories differ (WP-based). Need our own instruction text and guide.

### 14. Dependency Network Probe
**Fork:** devGPL
**Priority:** P3 | **Effort:** M

Before reporting schedule metrics, probes whether the project actually has a dependency network (linked + auto-scheduled tasks). A schedule with no links reports zero slack for everything, which reads as "everything critical" rather than "nothing computed." The probe adds a diagnostics block and warning to every schedule tool response.

**What to steal:** The `_probe_vista` / `_network_warning` pattern. Our `get_schedule_analysis`, `get_critical_path`, `what_if_delay` all silently return misleading data on unlinked schedules. This is a data quality improvement.

**Conflicts:** Needs integration with our response format. Their probe uses their view abstraction (`VistaCOM`); we'd need to adapt for our COM access pattern.

---

## SKIP

Things that duplicate or conflict with what we already built better.

### 15. Single-File Architecture
**Fork:** 4nswer
**Reason:** We deliberately moved to `src/` package with per-WP modules. The single-file approach (5,200 lines) doesn't scale with the hardening guarantees WP-1 through WP-6 provide. 4nswer's own memory-bank notes say "revisit only if it becomes unmanageable." It already is.

### 16. Calculation Suspension Pattern
**Fork:** devGPL (`calculo_suspenso` context manager)
**Reason:** We already have WP-4 `CalcPolicy` with `deferred_calc` context manager. Theirs is simpler (just `app.Calculation = 0` / `-1`), ours handles auto/manual mode selection and integrates with WP-3 verify-after-write. Our design is strictly better.

### 17. Basic _find_task / _uid_map
**Fork:** devGPL
**Reason:** We have WP-5 TaskStore with UniqueID resolution and stale proxy detection. Their `_uid_map` is a snapshot dict that doesn't detect stale COM references. Our TaskStore is the correct solution.

### 18. Memory Bank Protocol (CLAUDE.md)
**Fork:** 4nswer
**Reason:** Their CLAUDE.md implements a session-memory protocol for Cursor-style development (memory-bank/ directory with 6 files, read at session start). This is a development workflow convention, not a feature of the MCP server. Not applicable to our use case.

### 19. Legacy Test Suites (test_phase*.py)
**Fork:** Both forks carry them
**Reason:** We already have these plus WP-specific unit tests and the WP-8 integration harness with fixture generation and conftest. devGPL added `test_backend_parity.py` and `test_vistas_paridade.py` (fast-path parity tests), which are specific to their mpxj integration.

### 20. Tool Wrapper Removal (import_xml, export_xml, search_tasks)
**Fork:** 4nswer
**Reason:** They removed three thin wrappers and folded behavior into existing tools. We still have these wrappers but they're trivially thin. Not worth the breaking change for existing clients.

---

## PRIORITY SUMMARY

| # | Item | Fork | Effort | Priority | Category |
|---|------|------|--------|----------|----------|
| 3 | MSPROJECT_SAFE_ROOT | 4nswer | S | **P1** | Portable |
| 4 | MSPROJECT_DRY_RUN (env) | 4nswer | S | **P1** | Portable |
| 1 | pyproject.toml + console script | devGPL | S | **P1** | Portable |
| 5 | stderr-only logging | Both | S | **P1** | Portable |
| 9 | Response size management | devGPL | M | **P2** | Portable |
| 7 | COM retry with backoff | devGPL | S | **P2** | Portable |
| 6 | Schema size reduction | devGPL | S | **P2** | Portable |
| 8 | Improved error messages | devGPL | S | **P2** | Portable |
| 2 | server.json (MCP Registry) | devGPL | S | **P2** | Portable |
| 11 | Fast read path (mpxj) | devGPL | L | **P2** | Adaptation |
| 12 | ToolAnnotations | 4nswer | M | **P2** | Adaptation |
| 13 | Server instructions + guide | 4nswer | S | **P2** | Adaptation |
| 14 | Dependency network probe | devGPL | M | **P3** | Adaptation |
| 10 | Domain module split | devGPL | L | **P3** | Adaptation |

### Recommended Execution Order

**Sprint 1 (P1, all Small):** Items 3, 4, 1, 5 -- safety guardrails + packaging. Half a day.

**Sprint 2 (P2, S/M):** Items 7, 6, 8, 2, 13 -- reliability + discoverability. One day.

**Sprint 3 (P2, M):** Items 9, 12 -- response management + annotations. Two days (breaking change for response shape).

**Sprint 4 (P2, L):** Item 11 -- fast read path as WP-9. One week. Needs mpxj testing on real schedules.

---

## KEY OBSERVATIONS

1. **devGPL is the more mature fork.** 67 commits of real production hardening, measured on 8,000+ task schedules, with Portuguese-locale bugs found and fixed. Their changelog is exemplary -- every behavioral change documented with measurements.

2. **4nswer's safety layer is the highest-value steal.** SAFE_ROOT + DRY_RUN are exactly the right guardrails for an LLM-driven COM automation server. Simple, fail-closed, deployment-configurable.

3. **Neither fork has our WP hardening.** No verify-after-write, no TaskStore with stale detection, no CalcPolicy, no UILock, no ProjectSession lifecycle management. Our architecture is strictly more rigorous on the mutation path.

4. **devGPL's fast read path is the biggest performance win available.** 30-48s -> 1.6s for read-only scans. But it requires careful integration with our verify-after-write guarantees (WP-3) since it reads the saved file, not the live COM state.

5. **Response size is our biggest gap.** We return multi-MB JSON responses on real schedules. devGPL solved this comprehensively. This is blocking for production use with LLM clients.

6. **The mcp version ceiling (`<1.20`) is load-bearing.** Worth adopting immediately -- prevents the `cryptography` ARM64 build failure that would otherwise bite us on Windows on ARM.
