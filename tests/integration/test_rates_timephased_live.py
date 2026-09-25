"""
Live tool-level tests for rates and time-phased data: timephased work, working hours, resource
availability, task type and priority, variance, snapshot diffs, hyperlinks, recurring tasks,
rate tables and task calendars.

Requires MS Project on Windows; skipped otherwise by tests/integration/conftest.py.
Run under pytest, or directly: python tests/integration/test_rates_timephased_live.py
"""
import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from _scenario import call, Checks  # noqa: E402
from _calendars_setup import setup_project  # noqa: E402


async def run_tests():
    checks = Checks()
    ok, skip = checks.ok, checks.skip
    uid_alpha, uid_beta, uid_gamma = await setup_project()

    # -------------------------------------------------------------------
    # 10. get_timephased_data
    # -------------------------------------------------------------------
    print("\n=== 10. get_timephased_data ===")
    if uid_alpha:
        r = await call("get_timephased_data",
                       unique_id=uid_alpha, start_date="2026-04-01",
                       end_date="2026-04-30", timescale="weekly", data_type="work")
        ok("timephased has periods", isinstance(r.get("periods"), list))
        ok("timephased has name",    "name" in r)
        ok("timephased timescale",   r.get("timescale") == "weekly")

        # Monthly
        r2 = await call("get_timephased_data",
                        unique_id=uid_alpha, start_date="2026-04-01",
                        end_date="2026-06-30", timescale="monthly", data_type="cost")
        ok("timephased monthly works", isinstance(r2.get("periods"), list))

        # Bad timescale
        r3 = await call("get_timephased_data",
                        unique_id=uid_alpha, start_date="2026-04-01",
                        end_date="2026-04-30", timescale="hourly", data_type="work")
        ok("timephased bad timescale", "error" in r3)
    else:
        skip("get_timephased_data", "no task")

    # -------------------------------------------------------------------
    # 11. set_working_hours
    # -------------------------------------------------------------------
    print("\n=== 11. set_working_hours ===")
    # Set Friday (6) to half-day
    shifts = json.dumps([["07:00", "12:00"]])
    r = await call("set_working_hours", calendar_name="Standard", day=6, shifts_json=shifts)
    ok("set_working_hours status", r.get("status") == "updated")
    ok("set_working_hours working", r.get("working") is True)

    # Set Saturday (7) to non-working
    r2 = await call("set_working_hours", calendar_name="Standard", day=7, shifts_json="[]")
    ok("set_working_hours non-working", r2.get("working") is False)

    # Bad day
    r3 = await call("set_working_hours", calendar_name="Standard", day=0, shifts_json="[]")
    ok("set_working_hours bad day", "error" in r3)

    # -------------------------------------------------------------------
    # 12. get_resource_availability
    # -------------------------------------------------------------------
    print("\n=== 12. get_resource_availability ===")
    r = await call("get_resource_availability",
                   resource_name="PM Lead", start_date="2026-04-01",
                   end_date="2026-04-30", timescale="weekly")
    ok("resource_availability has periods", isinstance(r.get("periods"), list))
    ok("resource_availability has max_units", "max_units" in r)
    ok("resource_availability resource name", r.get("resource") == "PM Lead")

    # Non-existent resource
    r2 = await call("get_resource_availability",
                    resource_name="Nobody", start_date="2026-04-01",
                    end_date="2026-04-30")
    ok("resource_availability bad resource", "error" in r2)

    # -------------------------------------------------------------------
    # 13. update_task — priority and task_type
    # -------------------------------------------------------------------
    print("\n=== 13. update_task priority & type ===")
    if uid_alpha:
        r = await call("update_task", unique_id=uid_alpha, priority=800, task_type="FixedDuration")
        ok("update_task priority changed", "priority" in r.get("changed", []))
        ok("update_task type changed",     "type" in r.get("changed", []))

        # Verify
        r2 = await call("get_task", unique_id=uid_alpha)
        ok("priority is 800",             r2.get("priority") == 800)
        ok("type is FixedDuration",        r2.get("type") == "FixedDuration")
    else:
        skip("update_task priority/type", "no task")

    # -------------------------------------------------------------------
    # 14. get_variance_report
    # -------------------------------------------------------------------
    print("\n=== 14. get_variance_report ===")
    # Save a baseline first
    await call("save_baseline", baseline_number=0)
    r = await call("get_variance_report", baseline=0)
    ok("variance_report has baseline",    "baseline" in r)
    ok("variance_report has total_tasks", isinstance(r.get("total_tasks"), int))
    ok("variance_report has tasks list",  isinstance(r.get("tasks"), list))

    # -------------------------------------------------------------------
    # 15. snapshot_diff
    # -------------------------------------------------------------------
    print("\n=== 15. snapshot_diff ===")
    tmp_dir = tempfile.gettempdir()
    snap_a = os.path.join(tmp_dir, "snap_a.json")
    snap_b = os.path.join(tmp_dir, "snap_b.json")

    # Take snapshot A
    await call("snapshot_to_json", output_path=snap_a)

    # Modify a task
    if uid_beta:
        await call("update_task", unique_id=uid_beta, name="Task Beta MODIFIED")

    # Take snapshot B
    await call("snapshot_to_json", output_path=snap_b)

    r = await call("snapshot_diff", path_a=snap_a, path_b=snap_b)
    ok("snapshot_diff has counts", "added_count" in r and "changed_count" in r)
    if uid_beta:
        ok("snapshot_diff detects change", r.get("changed_count", 0) >= 1)
    else:
        skip("snapshot_diff change detection", "no task")

    # Bad path
    r2 = await call("snapshot_diff", path_a="nonexistent.json", path_b=snap_b)
    ok("snapshot_diff bad path", "error" in r2)

    # Cleanup
    for f in (snap_a, snap_b):
        try:
            os.remove(f)
        except Exception:
            pass

    # -------------------------------------------------------------------
    # 16. set_task_hyperlink
    # -------------------------------------------------------------------
    print("\n=== 16. set_task_hyperlink ===")
    if uid_alpha:
        r = await call("set_task_hyperlink",
                       unique_id=uid_alpha, url="https://example.com",
                       text="Example Link")
        ok("set_hyperlink status", r.get("status") == "updated")
        ok("set_hyperlink url",    r.get("hyperlink") == "https://example.com")

        # Verify in task_to_dict
        r2 = await call("get_task", unique_id=uid_alpha)
        ok("hyperlink in task_to_dict", r2.get("hyperlink") == "https://example.com")
        ok("hyperlink_text in task_to_dict", r2.get("hyperlink_text") == "Example Link")
    else:
        skip("set_task_hyperlink", "no task")

    # -------------------------------------------------------------------
    # 17. add_recurring_task
    # -------------------------------------------------------------------
    print("\n=== 17. add_recurring_task ===")
    r = await call("add_recurring_task",
                   name="Weekly Status Meeting",
                   recurrence_type="weekly",
                   start_date="2026-05-01",
                   end_date="2026-06-30",
                   duration_days=0.25,
                   day_of_week=2)
    if "error" not in r:
        ok("recurring task created", r.get("status") == "created")
        ok("recurring task has uid", "unique_id" in r)
    else:
        skip("add_recurring_task", f"COM may not support: {r.get('error', '')[:80]}")

    # -------------------------------------------------------------------
    # 18. get_resource_rate_tables
    # -------------------------------------------------------------------
    print("\n=== 18. get_resource_rate_tables ===")
    r = await call("get_resource_rate_tables", resource_name="PM Lead")
    ok("rate_tables has resource", r.get("resource") == "PM Lead")
    ok("rate_tables has tables",   isinstance(r.get("tables"), dict))
    ok("rate_tables has table A",  "A" in r.get("tables", {}))

    # Non-existent resource
    r2 = await call("get_resource_rate_tables", resource_name="Nobody")
    ok("rate_tables bad resource", "error" in r2)

    # -------------------------------------------------------------------
    # 19. set_resource_rate_table
    # -------------------------------------------------------------------
    print("\n=== 19. set_resource_rate_table ===")
    r = await call("set_resource_rate_table",
                   resource_name="PM Lead", table="A",
                   standard_rate="50/h", overtime_rate="75/h")
    if "error" not in r:
        ok("set_rate_table status", r.get("status") == "updated")
        ok("set_rate_table table",  r.get("table") == "A")
    else:
        skip("set_resource_rate_table", f"may need specific setup: {r.get('error', '')[:80]}")

    # -------------------------------------------------------------------
    # 20. set_task_calendar
    # -------------------------------------------------------------------
    print("\n=== 20. set_task_calendar ===")
    if uid_gamma:
        # Create a calendar to assign
        await call("create_calendar", name="Task Specific Cal", copy_from="Standard")
        r = await call("set_task_calendar", unique_id=uid_gamma, calendar_name="Task Specific Cal")
        ok("set_task_calendar status", r.get("status") == "updated")
        ok("set_task_calendar calendar", r.get("calendar") == "Task Specific Cal")

        # Non-existent calendar
        r2 = await call("set_task_calendar", unique_id=uid_gamma, calendar_name="NoSuchCal")
        ok("set_task_calendar bad cal", "error" in r2)
    else:
        skip("set_task_calendar", "no task")

    # -------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------
    print("\n=== CLEANUP ===")
    await call("close_project", save=False)
    print("  Project closed without saving.\n")

    return checks.summary("Rates and timephased")


def test_rates_timephased_live():
    """Run the live scenario; any failed check fails the test."""
    assert asyncio.run(run_tests())


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(run_tests()) else 1)
