# MS Project MCP — Hardening Work Packages

## First step gate

Before any work package begins:

1. Clone the repo on the MSI (Windows machine with Project 16+)
2. Confirm MS Project 16+ is installed and licensed
3. Run health_check against a throwaway .mpp
4. Nothing else proceeds until that works

## Work packages

### WP-1: Session ownership

**Objective:** One Project instance, one owner process, explicit attach/detach, refuse to start if another COM client is already bound.

**Acceptance criteria:**
- Server creates or attaches to exactly one Project.Application COM instance
- Explicit attach() and detach() lifecycle methods
- Server refuses to start if another COM client is already bound to Project
- Graceful cleanup on server shutdown (release COM references, quit Project if we started it)

**Key tasks:**
- Create ProjectSession class that wraps COM lifecycle
- Implement attach/detach with ownership tracking (PID-based or mutex)
- Add startup check: detect existing COM clients via ROT (Running Object Table) or process enumeration
- Add shutdown hook to release COM and optionally quit Project
- Expose session_info tool returning owner PID, project path, connection state

**Dependencies:** None (foundation for everything else)
**Complexity:** M
**Risks:** ROT detection on Windows can be flaky. May need fallback to process-name enumeration.

---

### WP-2: Active-project identity

**Objective:** Every mutating tool takes project_id or file path. Never trust "whatever is active." switch_project as a side effect is how you corrupt the wrong .mpp.

**Acceptance criteria:**
- All mutating tools require an explicit project identifier (file path or hash)
- Server validates the identifier matches the currently open project before mutating
- switch_project is a deliberate, explicit operation — never a side effect
- Mismatch returns an error, not a silent switch

**Key tasks:**
- Define project identity scheme (file path canonical form or SHA of path)
- Add project_id parameter to all mutating tool schemas
- Add validation layer: compare requested project_id to active project before any write
- Refactor switch_project to be explicit-only with confirmation
- Return clear error on mismatch: "requested X but active project is Y"

**Dependencies:** WP-1 (needs ProjectSession)
**Complexity:** L (touches every mutating tool)
**Risks:** Retrofitting project_id into existing tool signatures is tedious but mechanical.

---

### WP-3: Verify-after-write

**Objective:** After every mutation, re-read the fields you think you set and return {requested, actual, drifted}. Project will lie to you via recalculation.

**Acceptance criteria:**
- Every mutation returns a verification payload: {requested, actual, drifted}
- Drifted fields are flagged with the reason (recalculation, constraint, etc.) when detectable
- Agent can distinguish "write succeeded" from "write succeeded but Project changed the value"

**Key tasks:**
- Create verify_write() utility: takes field map, re-reads via COM, compares
- Integrate into all mutation tools as a post-write step
- Define drift detection: exact match, tolerance for dates (±1 day for scheduling), tolerance for durations
- Return structured payload in tool response
- Log drifts for debugging

**Dependencies:** WP-2 (needs stable project identity)
**Complexity:** M
**Risks:** Some fields recalculate asynchronously. May need a short delay or explicit calc before verify.

---

### WP-4: Calculate policy

**Objective:** Explicit calculate_project vs deferred calc. Do not let 40 COM writes trigger 40 full recalcs on a 10k-task file.

**Acceptance criteria:**
- Server can suppress automatic calculation during batch operations
- Explicit calculate_project tool triggers a full recalc on demand
- Batch operations defer calculation until explicitly requested
- Performance: 40 writes + 1 calc is faster than 40 writes with auto-calc

**Key tasks:**
- Set Application.Calculation = pjManualCalc at session start (or per-batch)
- Create calculate_project tool
- Add calc_mode parameter to batch operations (auto/manual/deferred)
- Restore original calc setting on session detach
- Document the tradeoff: deferred calc means intermediate reads may be stale

**Dependencies:** WP-2 (needs project identity for scoping)
**Complexity:** S
**Risks:** Some COM operations may force a calc regardless of the setting. Need to test empirically.

---

### WP-5: COM proxy refresh

**Objective:** Drop cached Task/Resource references after switch, save, or insert. Re-resolve by UniqueID every time.

**Acceptance criteria:**
- No cached COM object references survive a save, switch, or insert operation
- All task/resource access resolves by UniqueID at point of use
- Stale reference access returns a clear error, not a crash or wrong data

**Key tasks:**
- Create TaskStore class that resolves tasks by UniqueID on every access
- Invalidate any internal caches on save/switch/insert events
- Add COM error handling: detect RPC_E_DISCONNECTED and similar stale-proxy errors
- Re-resolve transparently on stale proxy detection (one retry, then error)
- Remove any global task/resource caches from existing code

**Dependencies:** WP-2 (needs project identity)
**Complexity:** M
**Risks:** UniqueID resolution requires iterating the Tasks collection each time. May need an index for performance on large files.

---

### WP-6: Concurrency and UI

**Objective:** Kill the "don't click the GUI" rule by making the server start Project invisible (Visible = False) for unattended work, or by locking the UI during a tool call.

**Acceptance criteria:**
- Server can run Project in invisible mode (Visible = False)
- OR: Server locks the UI during tool execution and unlocks after
- User clicking the GUI during a tool call does not corrupt state
- Mode is configurable: invisible (headless) vs. visible-but-locked

**Key tasks:**
- Add startup config: headless mode (Visible = False) vs. visible mode
- In visible mode: set Application.ScreenUpdating = False during tool calls
- Add try/finally to ensure ScreenUpdating is restored on error
- Test: open Project visible, run a tool, click around — no corruption
- Document the tradeoff: invisible mode is safer but user can't see progress

**Dependencies:** WP-1 (needs ProjectSession for lifecycle control)
**Complexity:** S
**Risks:** Some Project operations may force the window visible. Invisible mode may not work with all Project editions.

---

### WP-7: Idempotent bulk ops

**Objective:** Bulk add/update should be transactional from the agent's point of view: dry-run, apply, report failures per UniqueID, no silent partial success.

**Acceptance criteria:**
- Bulk operations support dry-run mode (validate without applying)
- Apply mode returns per-item results: {UniqueID, status, error}
- Partial failures are reported per item, not as a single error
- Agent can retry failed items without re-applying succeeded ones
- Operations are idempotent: applying the same bulk op twice produces the same result

**Key tasks:**
- Design bulk operation schema: [{action, target_uid, fields}]
- Implement dry-run: validate each item, return predicted results
- Implement apply: execute each item, capture per-item success/failure
- Add idempotency: check current state before applying, skip if already matches
- Wrap bulk ops in deferred calc (WP-4) automatically
- Use verify-after-write (WP-3) on each item
- Use COM proxy refresh (WP-5) between items if needed

**Dependencies:** WP-2, WP-3, WP-4, WP-5
**Complexity:** L
**Risks:** True transactional rollback is not possible with COM. "Transaction" here means reporting, not atomicity.

---

### WP-8: Tests without a human

**Objective:** Launch Project from the test harness, use a fixture .mpp, tear down.

**Acceptance criteria:**
- Test suite launches Project programmatically (no human setup)
- Uses fixture .mpp files (checked into repo)
- Tears down cleanly: quits Project, releases COM, deletes temp files
- Tests run in CI on a Windows runner with Project installed
- Each test gets a fresh Project instance (no cross-test contamination)

**Key tasks:**
- Create test fixtures: minimal .mpp files for each scenario
- Create test harness: launch Project, open fixture, run test, tear down
- Write tests for WP-1 through WP-7
- Add pytest conftest.py with Project session fixture
- Document CI setup: Windows runner requirements, Project license
- Add test workflow to GitHub Actions (or document manual test procedure)

**Dependencies:** WP-1 through WP-7 (tests validate all prior work)
**Complexity:** L
**Risks:** CI with Project requires a Windows runner with Project installed. May need to be local-only initially.

---

### WP-9: COM correctness and tool guardrails

**Objective:** Fix the defects found by testing every tool against a live MS Project instance.

**Status:** Implemented and re-verified against live MS Project; awaiting user validation.

**Key changes:**
- `src/tool_guardrails.py`: strict arguments, dry-run gate for every mutating tool, optional `project_id` guard, one error contract, Planning Wizard suppression, modal-dialog watchdog (`src/modal_guard.py`)
- `src/com_write.py`: UTC-safe COM dates (end-of-day finishes), `HoursPerDay`-based durations, save policy (`MSPROJECT_AUTOSAVE`, never on untitled projects), batched calc that restores the user's mode
- Correct Project enums from the type library (calculation, baselines, UpdateProject, timescales, link types, custom field IDs)
- Task edits via COM objects instead of view rows; move/copy verify the selection before cut/copy
- Integration fixtures never attach to (or quit) a user's running Project
- `ProjectSession.detach()` waits for a Project it launched to exit after Quit, so a dying instance is never adopted by the next attach (the cause of a leaked hidden instance)
- mpxj fast-read path works against MPXJ 14+ (`org.mpxj` classes via `jpype.JClass`); numbers keep their decimals, enums/Priority/Rate convert properly, predecessors carry the linked task, resource work and cost are summed from assignments, and resource-less placeholder assignments are skipped. Verified live against Project by `tests/integration/test_mpxj_live.py`
- Every `.py` file kept at 300 lines or fewer

---

## Not in scope (deferred)

- Adding another 40 tools — stabilize the foundation first
- Wrapping the GUI with UI Automation — COM already exposes the object model
- Targeting Project for the Web — different API surface entirely
- Keeping everything in one Python file — will extract layers as part of WP-1/WP-2

## Language decision

Python + pywin32 is fine for a hardened fork. C# with the official MCP SDK is cleaner long-term on Windows, but it is a rewrite, not a fork. **Fork first, extract a ProjectSession + TaskStore layer, then decide if the language is the bottleneck.**
