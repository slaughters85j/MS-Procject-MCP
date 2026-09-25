"""
Live tool-level tests for project structure: baseline comparison, dependency chains,
resource assignment and updates, moving and copying tasks, and WBS progress.

Requires MS Project on Windows; skipped otherwise by tests/integration/conftest.py.
Run under pytest, or directly: python tests/integration/test_structure_export_live.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _scenario import call, Checks  # noqa: E402
from _structure_setup import setup_project  # noqa: E402


async def run_tests():
    checks = Checks()
    ok, skip = checks.ok, checks.skip
    main_project_name, uid = await setup_project()

    # -----------------------------------------------------------------------
    # Tests
    # -----------------------------------------------------------------------
    print("\n=== STRUCTURE AND EXPORT TESTS ===")

    # 1. compare_baselines
    r = await call("compare_baselines", baseline_a=0, baseline_b=-1)
    has_variance = r.get("summary", {}).get("tasks_with_variance", 0) > 0
    ok("1. compare_baselines", has_variance, f"variance tasks: {r.get('summary', {}).get('tasks_with_variance')}")

    # 2. get_dependency_chain — successors from A
    r = await call("get_dependency_chain", unique_id=uid["Task A"], direction="successors")
    chain_names = [e["name"] for e in r.get("chain", [])]
    ok("2. get_dependency_chain (successors)",
       "Task B" in chain_names and "Task C" in chain_names,
       f"chain: {chain_names}")

    # 3. get_dependency_chain — predecessors from D
    r = await call("get_dependency_chain", unique_id=uid["Task D"], direction="predecessors")
    chain_names = [e["name"] for e in r.get("chain", [])]
    ok("3. get_dependency_chain (predecessors)",
       "Task C" in chain_names and "Task B" in chain_names,
       f"chain: {chain_names}")

    # 4. bulk_assign_resources
    assign_data = json.dumps([
        {"task_unique_id": uid["Sub-task D1"], "resource_name": "Alice"},
        {"task_unique_id": uid["Sub-task D2"], "resource_name": "Bob"},
        {"task_unique_id": uid["Milestone X"], "resource_name": "NewRes"},
    ])
    r = await call("bulk_assign_resources", assignments_json=assign_data)
    ok("4. bulk_assign_resources", r.get("assigned") == 3, f"assigned: {r.get('assigned')}")

    # 5. remove_resource_assignment
    r = await call("remove_resource_assignment", task_unique_id=uid["Sub-task D1"], resource_name="Alice")
    ok("5a. remove_resource_assignment", r.get("status") == "removed", f"status: {r.get('status')}")
    r2 = await call("remove_resource_assignment", task_unique_id=uid["Sub-task D1"], resource_name="NonExistent")
    ok("5b. remove_resource_assignment (invalid)", "error" in r2, "expected error for non-existent")

    # 6. update_resource
    r = await call("update_resource", resource_name="Charlie", max_units=2.0)
    ok("6. update_resource", "max_units" in r.get("changed", []), f"changed: {r.get('changed')}")

    # 7. move_task — move Milestone Y to after Task A
    r = await call("move_task", unique_id=uid["Milestone Y"], after_unique_id=uid["Task A"])
    ok("7. move_task", r.get("status") == "moved", f"status: {r.get('status')}, new_id: {r.get('new_id')}")

    # 8. get_progress_by_wbs
    r = await call("get_progress_by_wbs", max_level=2)
    branches = r.get("branches", [])
    ok("8. get_progress_by_wbs", len(branches) > 0, f"branches: {len(branches)}")

    # 9. copy_task_structure — copy Programme Alpha subtree
    r = await call("copy_task_structure", source_unique_id=uid["Programme Alpha"])
    copied = r.get("copied_tasks", [])
    ok("9. copy_task_structure", len(copied) > 0, f"copied: {len(copied)} tasks")

    # -----------------------------------------------------------------------
    # Cleanup
    # -----------------------------------------------------------------------
    print("\n=== CLEANUP ===")
    # Close all test projects
    for proj_name in ["Structure Export Test"]:
        try:
            await call("switch_project", name_or_index=proj_name)
            await call("close_project", save=False)
            print(f"  Closed {proj_name}")
        except Exception:
            # Project may not exist or COM stale — try direct close
            try:
                await call("close_project", save=False)
                print(f"  Closed active project (was {proj_name})")
            except Exception:
                pass
    print("  Cleanup done")

    return checks.summary("Structure")


def test_structure_export_live():
    """Run the live scenario; any failed check fails the test."""
    assert asyncio.run(run_tests())


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(run_tests()) else 1)
