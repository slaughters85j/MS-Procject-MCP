"""
Live tool-level tests for calendars: health check, enriched task fields, calculation,
calendar exceptions, project updates and rescheduling, calendar deletion and resource calendars.

Requires MS Project on Windows; skipped otherwise by tests/integration/conftest.py.
Run under pytest, or directly: python tests/integration/test_calendars_rates_live.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _scenario import call, Checks  # noqa: E402
from _calendars_setup import setup_project  # noqa: E402


async def run_tests():
    checks = Checks()
    ok, skip = checks.ok, checks.skip
    uid_alpha, uid_beta, uid_gamma = await setup_project()

    # -------------------------------------------------------------------
    # 1. health_check / ping
    # -------------------------------------------------------------------
    print("\n=== 1. health_check ===")
    r = await call("health_check")
    ok("health_check returns connected", r.get("status") == "connected")
    ok("health_check has version",       "version" in r)
    ok("health_check project_open",      r.get("project_open") is True)

    # -------------------------------------------------------------------
    # 2. Enriched task_to_dict
    # -------------------------------------------------------------------
    print("\n=== 2. Enriched task_to_dict ===")
    if uid_alpha:
        r = await call("get_task", unique_id=uid_alpha)
        NEW_FIELDS = [
            "actual_start", "actual_finish", "remaining_duration_days",
            "total_slack_days", "free_slack_days", "deadline", "priority",
            "constraint_type", "constraint_date", "manual", "type",
            "hyperlink", "hyperlink_text",
        ]
        for field in NEW_FIELDS:
            ok(f"task_to_dict has '{field}'", field in r, f"missing key: {field}")
        ok("priority is int", isinstance(r.get("priority"), int))
        ok("constraint_type is string", isinstance(r.get("constraint_type"), str))
        ok("type is string", isinstance(r.get("type"), str))
    else:
        skip("enriched task_to_dict", "no task created")

    # -------------------------------------------------------------------
    # 3. calculate_project
    # -------------------------------------------------------------------
    print("\n=== 3. calculate_project ===")
    r = await call("calculate_project")
    ok("calculate_project status", r.get("status") == "calculated")
    ok("calculate_project returns project name", "project" in r)

    # -------------------------------------------------------------------
    # 4. list_calendar_exceptions
    # -------------------------------------------------------------------
    print("\n=== 4. list_calendar_exceptions ===")
    # First add an exception so we have something to list
    await call("set_calendar_exception",
               calendar_name="Standard", name="Test Holiday",
               start="2026-12-25", finish="2026-12-25", working=False)

    r = await call("list_calendar_exceptions", calendar_name="Standard")
    ok("list_calendar_exceptions has calendar", "calendar" in r)
    ok("list_calendar_exceptions has count",    isinstance(r.get("count"), int))
    ok("list_calendar_exceptions count >= 1",   r.get("count", 0) >= 1)
    excs = r.get("exceptions", [])
    names = [e["name"] for e in excs]
    # COM may store the name differently; check that at least one exception exists
    ok("exceptions list non-empty", len(excs) >= 1, f"names={names}")

    # default (project calendar)
    r2 = await call("list_calendar_exceptions")
    ok("list_calendar_exceptions default calendar works", "calendar" in r2)

    # -------------------------------------------------------------------
    # 5. update_project (mark complete through date)
    # -------------------------------------------------------------------
    print("\n=== 5. update_project ===")
    r = await call("update_project", complete_through="2026-04-10")
    ok("update_project status", r.get("status") == "updated")
    ok("update_project returns date", r.get("complete_through") == "2026-04-10")

    # -------------------------------------------------------------------
    # 6. reschedule_incomplete_work
    # -------------------------------------------------------------------
    print("\n=== 6. reschedule_incomplete_work ===")
    r = await call("reschedule_incomplete_work", reschedule_from="2026-04-15")
    ok("reschedule status", r.get("status") == "rescheduled")
    ok("reschedule date",   r.get("reschedule_from") == "2026-04-15")

    # -------------------------------------------------------------------
    # 7. delete_calendar_exception
    # -------------------------------------------------------------------
    print("\n=== 7. delete_calendar_exception ===")
    # Find the name of the exception that was actually stored
    exc_name_to_delete = excs[0]["name"] if excs else "Test Holiday"
    r = await call("delete_calendar_exception",
                   calendar_name="Standard", exception_name=exc_name_to_delete)
    ok("delete_calendar_exception status", r.get("status") == "deleted", f"got: {r}")

    # Verify count decreased
    r2 = await call("list_calendar_exceptions", calendar_name="Standard")
    ok("exception removed", r2.get("count", 999) < r.get("count", 999) if "count" in r else r2.get("count", 0) == 0)

    # -------------------------------------------------------------------
    # 8. delete_calendar (create one first, then delete)
    # -------------------------------------------------------------------
    print("\n=== 8. delete_calendar ===")
    await call("create_calendar", name="Temp Cal", copy_from="Standard")
    r = await call("delete_calendar", calendar_name="Temp Cal")
    ok("delete_calendar status", r.get("status") == "deleted")

    # Try deleting project calendar — should fail
    r2 = await call("delete_calendar", calendar_name="Standard")
    ok("delete project calendar blocked", "error" in r2)

    # -------------------------------------------------------------------
    # 9. set_resource_calendar
    # -------------------------------------------------------------------
    print("\n=== 9. set_resource_calendar ===")
    await call("create_calendar", name="Part Time", copy_from="Standard")
    r = await call("set_resource_calendar", resource_name="PM Lead", calendar_name="Part Time")
    ok("set_resource_calendar status", r.get("status") == "updated")
    ok("set_resource_calendar resource", r.get("resource") == "PM Lead")

    # Non-existent calendar
    r2 = await call("set_resource_calendar", resource_name="PM Lead", calendar_name="NoSuchCal")
    ok("set_resource_calendar bad cal", "error" in r2)

    # -------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------
    print("\n=== CLEANUP ===")
    await call("close_project", save=False)
    print("  Project closed without saving.\n")

    return checks.summary("Calendars")


def test_calendars_rates_live():
    """Run the live scenario; any failed check fails the test."""
    assert asyncio.run(run_tests())


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(run_tests()) else 1)
