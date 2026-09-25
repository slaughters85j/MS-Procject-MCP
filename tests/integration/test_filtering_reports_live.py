"""
Live tool-level tests for custom field values, schedule validation, milestones, resource
workload, leveling, deadlines, task activation and bulk dry runs.

Requires MS Project on Windows; skipped otherwise by tests/integration/conftest.py.
Run under pytest, or directly: python tests/integration/test_filtering_reports_live.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _filtering_common import call, setup_project, finish  # noqa: E402


async def run_tests():
    results = {}
    main_project_name, task_uids = await setup_project()

    # ===================================================================
    # Test 8: get_custom_field_values
    # ===================================================================
    print("\n=== Test 8: get_custom_field_values ===")
    try:
        # Query Text1 (RAG field) — should have Green, Amber, Red from setup
        r = await call("get_custom_field_values", {"field_name": "Text1"})
        assert r["total_tasks"] > 0, "No tasks found"
        print(f"  Text1 values: {r['unique_values']}")
        print(f"  Counts: {r['value_counts']}")
        # We set Green, Amber, Red — at least those should exist
        for rag in ["Green", "Amber", "Red"]:
            assert rag in r["value_counts"], f"Missing '{rag}' in Text1 values"
        print("  Verified: Green, Amber, Red all present")

        results["get_custom_field_values"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        results["get_custom_field_values"] = "FAIL"

    # ===================================================================
    # Test 9: validate_schedule
    # ===================================================================
    print("\n=== Test 9: validate_schedule ===")
    try:
        r = await call("validate_schedule")
        assert "health_score" in r, "Missing health_score"
        assert "issues" in r, "Missing issues"
        assert r["summary"]["total_tasks"] > 0, "No tasks found"
        print(f"  Health score: {r['health_score']}")
        print(f"  Total tasks: {r['summary']['total_tasks']}, Total issues: {r['summary']['total_issues']}")
        for cat, data in r["issues"].items():
            if data["count"] > 0:
                print(f"    {cat}: {data['count']}")

        # We have tasks without resources (like Planning, Execution) — verify detection
        assert r["issues"]["no_resources"]["count"] > 0, "Should detect tasks without resources"
        print(f"  Verified: no_resources detected ({r['issues']['no_resources']['count']})")

        results["validate_schedule"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        results["validate_schedule"] = "FAIL"

    # ===================================================================
    # Test 10: get_milestone_report
    # ===================================================================
    print("\n=== Test 10: get_milestone_report ===")
    try:
        r = await call("get_milestone_report", {"days_ahead": 365, "upcoming_count": 5})
        assert r["total_milestones"] >= 1, f"Expected >= 1 milestone, got {r['total_milestones']}"
        print(f"  Total milestones: {r['total_milestones']}")
        print(f"  By status: {r['by_status']}")
        if r["upcoming"]:
            print(f"  Upcoming: {r['upcoming'][0]['name']} ({r['upcoming'][0]['finish']})")
        results["get_milestone_report"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        results["get_milestone_report"] = "FAIL"

    # ===================================================================
    # Test 11: get_resource_workload
    # ===================================================================
    print("\n=== Test 11: get_resource_workload ===")
    try:
        r = await call("get_resource_workload", {"resource_name": "Alice"})
        assert len(r["assignments"]) >= 2, f"Alice should have >= 2 assignments, got {len(r['assignments'])}"
        print(f"  Alice: {len(r['assignments'])} assignments, overallocated={r['overallocated']}")
        for a in r["assignments"]:
            print(f"    {a['task_name']}: {a['start']} - {a['finish']}")
        if r["conflicts"]:
            print(f"  Conflicts: {len(r['conflicts'])}")

        # Test invalid resource
        r2 = await call("get_resource_workload", {"resource_name": "NONEXISTENT"})
        assert "error" in r2, "Expected error for invalid resource"
        print("  Invalid resource handled correctly")

        results["get_resource_workload"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        results["get_resource_workload"] = "FAIL"

    # ===================================================================
    # Test 12: level_resources
    # ===================================================================
    print("\n=== Test 12: level_resources ===")
    try:
        r = await call("level_resources")
        assert r["status"] == "leveled", f"Expected leveled, got {r}"
        print(f"  Leveled project: {r['project']}")
        results["level_resources"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        results["level_resources"] = "FAIL"

    # ===================================================================
    # Test 13: set_deadline
    # ===================================================================
    print("\n=== Test 13: set_deadline ===")
    try:
        uid = task_uids["Build Work"]
        # Set deadline
        r = await call("set_deadline", {"unique_id": uid, "deadline_date": "2026-07-15"})
        assert r["status"] == "set", f"Expected set, got {r}"
        assert r["deadline"] == "2026-07-15"
        print(f"  Set deadline on '{r['name']}': {r['deadline']}, missed={r['deadline_missed']}")

        # Set a tight deadline that should be missed
        r = await call("set_deadline", {"unique_id": uid, "deadline_date": "2026-04-01"})
        print(f"  Tight deadline: missed={r['deadline_missed']}")

        # Clear deadline
        r = await call("set_deadline", {"unique_id": uid, "deadline_date": "clear"})
        assert r["status"] == "cleared", f"Expected cleared, got {r}"
        print("  Deadline cleared")

        results["set_deadline"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        results["set_deadline"] = "FAIL"

    # ===================================================================
    # Test 14: set_task_active
    # ===================================================================
    print("\n=== Test 14: set_task_active ===")
    try:
        uid = task_uids["Execution"]
        # Deactivate
        r = await call("set_task_active", {"unique_id": uid, "active": False})
        assert r["status"] == "updated", f"Expected updated, got {r}"
        assert r["active"] is False, "Task should be inactive"
        print(f"  Deactivated '{r['name']}'")

        # Verify via get_task
        t = await call("get_task", {"unique_id": uid})
        assert t["active"] is False, f"get_task shows active={t['active']}, expected False"
        print(f"  Verified: active={t['active']}")

        # Reactivate
        r = await call("set_task_active", {"unique_id": uid, "active": True})
        assert r["active"] is True, "Task should be active"
        print(f"  Reactivated '{r['name']}'")

        results["set_task_active"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        results["set_task_active"] = "FAIL"

    # ===================================================================
    # Test 15: dry_run_bulk_update
    # ===================================================================
    print("\n=== Test 15: dry_run_bulk_update ===")
    try:
        updates = [
            {"unique_id": task_uids["Design Work"], "rag": "Red", "percent_complete": 50},
            {"unique_id": task_uids["Build Work"], "name": "Construction Phase"},
            {"unique_id": 999999, "rag": "Green"},  # non-existent
        ]
        r = await call("dry_run_bulk_update", {"updates_json": json.dumps(updates)})
        assert r["preview"] is True, "Should be a preview"
        assert r["total_tasks_affected"] >= 2, f"Expected >= 2 affected, got {r['total_tasks_affected']}"
        assert 999999 in r["not_found"], "Should report 999999 as not found"
        print(f"  Preview: {r['total_changes']} changes across {r['total_tasks_affected']} tasks")
        print(f"  Not found: {r['not_found']}")

        # Verify NO actual mutation happened
        t = await call("get_task", {"unique_id": task_uids["Design Work"]})
        assert t["rag"] != "Red" or t["rag"] == "Green", "Design Work RAG should NOT have changed from dry run"
        assert t["percent_complete"] == 0, f"Design Work % should still be 0, got {t['percent_complete']}"
        print(f"  Verified: no mutation occurred (RAG={t['rag']}, %={t['percent_complete']})")

        t2 = await call("get_task", {"unique_id": task_uids["Build Work"]})
        assert t2["name"] == "Build Work", f"Build Work name should NOT have changed, got '{t2['name']}'"
        print(f"  Verified: Build Work name unchanged ('{t2['name']}')")

        results["dry_run_bulk_update"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        results["dry_run_bulk_update"] = "FAIL"

    return await finish(results, "FILTERING REPORTS TEST SUMMARY")


def test_filtering_reports_live():
    """Run the live scenario; any failed check fails the test."""
    assert asyncio.run(run_tests())


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(run_tests()) else 1)
