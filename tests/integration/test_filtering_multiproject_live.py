"""
Live tool-level tests for project switching, filter and group queries, calendar writes
and custom fields.

Requires MS Project on Windows; skipped otherwise by tests/integration/conftest.py.
Run under pytest, or directly: python tests/integration/test_filtering_multiproject_live.py
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
    # Test 1: list_projects
    # ===================================================================
    print("\n=== Test 1: list_projects ===")
    try:
        r = await call("list_projects")
        assert r["count"] >= 1, f"Expected >= 1 project, got {r['count']}"
        assert r["active"], "No active project"
        proj = r["projects"][0]
        assert "name" in proj and "task_count" in proj and "start" in proj
        has_active = any(p["is_active"] for p in r["projects"])
        assert has_active, "No project marked as active"
        print(f"  Count: {r['count']}, Active: {r['active']}")
        results["list_projects"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        results["list_projects"] = "FAIL"

    # ===================================================================
    # Test 2: switch_project (open 2nd project, switch, switch back)
    # ===================================================================
    print("\n=== Test 2: switch_project ===")
    try:
        # Create a second project
        r2 = await call("new_project", {"title": "Switch Test", "start": "2026-01-01"})
        proj2_name = r2["name"]
        print(f"  Created 2nd project: {proj2_name}")

        # Switch back to first by name substring (use actual name)
        r = await call("switch_project", {"name_or_index": main_project_name})
        assert r["status"] in ("switched", "already_active"), f"Unexpected status: {r['status']}"
        print(f"  Switched to: {r['name']}")

        # Switch by index to project 2
        # Find which index the 2nd project is at
        lp = await call("list_projects")
        proj2_idx = None
        for p in lp["projects"]:
            if p["name"] == proj2_name:
                proj2_idx = str(p["index"])
                break
        assert proj2_idx, f"Could not find {proj2_name} in project list"
        r = await call("switch_project", {"name_or_index": proj2_idx})
        assert r["status"] == "switched", f"Expected switched, got {r['status']}"
        print(f"  Switched by index to: {r['name']}")

        # Test invalid name
        r = await call("switch_project", {"name_or_index": "NONEXISTENT_XYZ"})
        assert "error" in r, "Expected error for invalid name"
        print(f"  Invalid name handled: {r['error'][:50]}")

        # Switch back to main project for remaining tests
        await call("switch_project", {"name_or_index": main_project_name})
        print(f"  Switched back to: {main_project_name}")

        results["switch_project"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        results["switch_project"] = "FAIL"
    finally:
        # Safety: always ensure we're back on the main project
        try:
            await call("switch_project", {"name_or_index": main_project_name})
        except Exception:
            pass

    # ===================================================================
    # Test 3: filter_tasks
    # ===================================================================
    print("\n=== Test 3: filter_tasks ===")
    try:
        # Filter by outline_level
        r = await call("filter_tasks", {"filters_json": json.dumps({"outline_level": 2, "summary": False})})
        assert r["pagination"]["total"] > 0, "No tasks at outline level 2"
        print(f"  Level 2 tasks: {r['pagination']['total']}")

        # Filter milestones
        r = await call("filter_tasks", {"filters_json": json.dumps({"milestone": True})})
        assert r["pagination"]["total"] >= 1, "No milestones found"
        print(f"  Milestones: {r['pagination']['total']}")

        # Test pagination
        r = await call("filter_tasks", {"filters_json": json.dumps({"limit": 2, "offset": 0})})
        assert r["pagination"]["returned"] <= 2, f"Limit not respected: got {r['pagination']['returned']}"
        print(f"  Pagination: returned={r['pagination']['returned']}, total={r['pagination']['total']}")

        # Filter by RAG
        r = await call("filter_tasks", {"filters_json": json.dumps({"rag": "Red"})})
        assert r["pagination"]["total"] >= 1, "No Red RAG tasks"
        print(f"  Red RAG tasks: {r['pagination']['total']}")

        results["filter_tasks"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        results["filter_tasks"] = "FAIL"

    # ===================================================================
    # Test 4: group_tasks_by
    # ===================================================================
    print("\n=== Test 4: group_tasks_by ===")
    try:
        # Group by outline_level
        r = await call("group_tasks_by", {"field": "outline_level"})
        total_from_groups = sum(g["count"] for g in r["groups"])
        assert total_from_groups == r["total_tasks"], f"Group counts don't sum: {total_from_groups} vs {r['total_tasks']}"
        print(f"  By outline_level: {len(r['groups'])} groups, {r['total_tasks']} tasks")

        # Group by milestone
        r = await call("group_tasks_by", {"field": "milestone"})
        print(f"  By milestone: {[(g['value'], g['count']) for g in r['groups']]}")

        # Group by critical
        r = await call("group_tasks_by", {"field": "critical"})
        print(f"  By critical: {[(g['value'], g['count']) for g in r['groups']]}")

        results["group_tasks_by"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        results["group_tasks_by"] = "FAIL"

    # ===================================================================
    # Test 5: set_calendar_exception
    # ===================================================================
    print("\n=== Test 5: set_calendar_exception ===")
    try:
        r = await call("set_calendar_exception", {
            "calendar_name": "Standard",
            "name": "Test Holiday",
            "start": "2026-12-25",
            "finish": "2026-12-25",
            "working": False,
        })
        assert r.get("status") == "created", f"Expected created, got: {r}"
        print(f"  Exception added: {r['exception']} on {r['start']}")

        # Test invalid calendar
        r = await call("set_calendar_exception", {
            "calendar_name": "FAKE_CALENDAR",
            "name": "Test",
            "start": "2026-01-01",
            "finish": "2026-01-01",
        })
        assert "error" in r, "Expected error for invalid calendar"
        print("  Invalid calendar handled correctly")

        results["set_calendar_exception"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        results["set_calendar_exception"] = "FAIL"

    # ===================================================================
    # Test 6: set_project_calendar
    # ===================================================================
    print("\n=== Test 6: set_project_calendar ===")
    try:
        # First get available calendars
        cals = await call("get_calendars")
        active_cal = cals["active_calendar"]
        other_cal = None
        for c in cals["calendars"]:
            if c != active_cal:
                other_cal = c
                break

        if not other_cal:
            # Only one calendar — test set to same (should still work)
            r = await call("set_project_calendar", {"calendar_name": active_cal})
            assert r["status"] == "updated", f"Expected updated, got {r}"
            print(f"  Only one calendar '{active_cal}' — set to same, status OK")

            # Test invalid calendar
            r = await call("set_project_calendar", {"calendar_name": "FAKE_CAL_XYZ"})
            assert "error" in r, "Expected error for invalid calendar"
            print("  Invalid calendar handled correctly")
        else:
            # Switch to other calendar
            r = await call("set_project_calendar", {"calendar_name": other_cal})
            assert r["status"] == "updated", f"Expected updated, got {r}"
            assert r["calendar"] == other_cal
            print(f"  Switched to '{other_cal}' from '{r['previous']}'")

            # Switch back
            r = await call("set_project_calendar", {"calendar_name": active_cal})
            assert r["status"] == "updated"
            print(f"  Switched back to '{active_cal}'")

        results["set_project_calendar"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        results["set_project_calendar"] = "FAIL"

    # ===================================================================
    # Test 7: update_custom_fields
    # ===================================================================
    print("\n=== Test 7: update_custom_fields ===")
    try:
        uid = task_uids["Design Work"]
        r = await call("update_custom_fields", {
            "unique_id": uid,
            "fields_json": json.dumps({
                "Text5": "Phase A",
                "Number1": 42,
                "Flag3": True,
            }),
        })
        assert r["status"] == "updated", f"Expected updated, got {r}"
        if r["errors"]:
            print(f"  Errors: {r['errors']}")
        assert len(r["changed"]) == 3, f"Expected 3 changes, got {len(r['changed'])}. Errors: {r['errors']}"
        assert len(r["errors"]) == 0, f"Unexpected errors: {r['errors']}"
        print(f"  Set 3 custom fields on '{r['name']}': {[c['field'] for c in r['changed']]}")

        # Verify Text5 via get_custom_field_values
        r2 = await call("get_custom_field_values", {"field_name": "Text5"})
        assert "Phase A" in r2["unique_values"], f"'Phase A' not in Text5 values: {r2['unique_values']}"
        print("  Verified Text5 contains 'Phase A'")

        results["update_custom_fields"] = "PASS"
    except Exception as e:
        print(f"  FAIL: {e}")
        results["update_custom_fields"] = "FAIL"

    return await finish(results, "FILTERING AND MULTI-PROJECT TEST SUMMARY")


def test_filtering_multiproject_live():
    """Run the live scenario; any failed check fails the test."""
    assert asyncio.run(run_tests())


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(run_tests()) else 1)
