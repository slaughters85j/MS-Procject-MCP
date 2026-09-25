"""
Live tool-level tests for export and multi-project work: CSV export, deadlines, slack,
task calendars, cost summary, undo, calendars, filters, JSON snapshots, cross-project links
and subprojects.

Requires MS Project on Windows; skipped otherwise by tests/integration/conftest.py.
Run under pytest, or directly: python tests/integration/test_export_multiproject_live.py
"""
import asyncio
import datetime
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from _scenario import call, Checks  # noqa: E402
from _structure_setup import setup_project  # noqa: E402


async def run_tests():
    checks = Checks()
    ok, skip = checks.ok, checks.skip
    main_project_name, uid = await setup_project()

    # 11. export_csv
    tmp_csv = os.path.join(tempfile.gettempdir(), "structure_export_test_export.csv")
    r = await call("export_csv", output_path=tmp_csv)
    ok("11. export_csv", r.get("rows", 0) > 0 and os.path.exists(tmp_csv), f"rows: {r.get('rows')}")
    if os.path.exists(tmp_csv):
        os.remove(tmp_csv)

    # 12. bulk_set_deadlines
    dl_data = json.dumps([
        {"unique_id": uid["Task A"], "deadline_date": "2026-04-20"},
        {"unique_id": uid["Task B"], "deadline_date": "2026-05-10"},
        {"unique_id": uid["Task C"], "deadline_date": "2026-06-01"},
        {"unique_id": uid["Task A"], "deadline_date": "clear"},  # clear the one we just set
    ])
    r = await call("bulk_set_deadlines", deadlines_json=dl_data)
    ok("12. bulk_set_deadlines", r.get("set", 0) >= 2 and r.get("cleared", 0) >= 1,
       f"set: {r.get('set')}, cleared: {r.get('cleared')}")

    # 13. find_available_slack
    r = await call("find_available_slack", min_days=0)
    ok("13. find_available_slack", isinstance(r.get("tasks"), list), f"count: {r.get('count')}")

    # 14. set_task_calendar
    try:
        r = await call("set_task_calendar", unique_id=uid["Task C"], calendar_name="Standard")
        ok("14a. set_task_calendar (set)", r.get("status") == "updated", f"status: {r.get('status')}")
        r2 = await call("set_task_calendar", unique_id=uid["Task C"], calendar_name="")
        ok("14b. set_task_calendar (clear)", r2.get("status") == "updated", f"status: {r2.get('status')}")
    except Exception as e:
        skip("14. set_task_calendar", str(e))

    # 15. get_cost_summary
    r = await call("get_cost_summary")
    ok("15. get_cost_summary", "totals" in r and "by_resource" in r, f"keys: {list(r.keys())}")

    # 16. undo_last
    await call("update_task", unique_id=uid["Task A"], notes="UNDO TEST MARKER")
    r = await call("undo_last", count=1)
    ok("16. undo_last", r.get("status") == "undone", f"undo_count: {r.get('undo_count')}")

    # 17. create_calendar
    r = await call("create_calendar", name="Test Cal", copy_from="Standard")
    ok("17. create_calendar", r.get("status") == "created" and "Test Cal" in r.get("calendars", []),
       f"calendars: {r.get('calendars')}")

    # 19. apply_filter
    try:
        r = await call("apply_filter", filter_name="Critical")
        ok("19a. apply_filter (Critical)", r.get("status") == "applied", f"status: {r.get('status')}")
        r2 = await call("apply_filter", filter_name="All Tasks")
        ok("19b. apply_filter (All Tasks)", r2.get("status") == "applied", f"status: {r2.get('status')}")
    except Exception as e:
        skip("19. apply_filter", str(e))

    # 20. snapshot_to_json
    tmp_json = os.path.join(tempfile.gettempdir(), "structure_export_test_snapshot.json")
    r = await call("snapshot_to_json", output_path=tmp_json)
    snapshot_ok = r.get("tasks", 0) > 0 and os.path.exists(tmp_json)
    if snapshot_ok:
        with open(tmp_json, "r") as fp:
            snap = json.load(fp)
        snapshot_ok = len(snap.get("tasks", [])) == r["tasks"]
    ok("20. snapshot_to_json", snapshot_ok, f"tasks: {r.get('tasks')}")
    if os.path.exists(tmp_json):
        os.remove(tmp_json)

    # -----------------------------------------------------------------------
    # Multi-project tests (run last to avoid COM proxy corruption)
    # -----------------------------------------------------------------------

    # 10. cross_project_link — create a 2nd project via COM, link tasks across them
    try:
        import win32com.client
        app = win32com.client.GetActiveObject("MSProject.Application")
        app.FileNew(SummaryInfo=False)
        xlink_proj = app.ActiveProject
        xlink_proj.Title = "Structure Export Xlink"
        xt = xlink_proj.Tasks.Add("External Task")
        xt.Start = datetime.datetime(2026, 7, 1)
        xt.Duration = 10 * 480
        xlink_uid = xt.UniqueID
        xlink_name = xlink_proj.Name

        r = await call("cross_project_link",
                       source_project=main_project_name,
                       source_unique_id=uid["Task A"],
                       target_project=xlink_name,
                       target_unique_id=xlink_uid)
        ok("10. cross_project_link", r.get("status") == "linked", str(r))

        app.FileClose(Save=0)
    except Exception as e:
        ok("10. cross_project_link", False, str(e))

    # 18. insert_subproject — create fixture .mpp via COM, insert into main
    try:
        import win32com.client
        tmp_mpp = os.path.join(tempfile.gettempdir(), "structure_export_subproject_fixture.mpp")

        app = win32com.client.GetActiveObject("MSProject.Application")
        app.FileNew(SummaryInfo=False)
        sub_proj = app.ActiveProject
        sub_proj.Title = "Subproject Fixture"
        st = sub_proj.Tasks.Add("Sub Work")
        st.Start = datetime.datetime(2026, 8, 1)
        st.Duration = 5 * 480
        app.FileSaveAs(Name=tmp_mpp, Format=0, Backup=False, ReadOnly=False)
        app.FileClose(Save=0)

        # Re-activate main
        for i in range(1, app.Projects.Count + 1):
            if main_project_name.lower() in app.Projects(i).Name.lower():
                app.WindowActivate(WindowName=app.Projects(i).Name)  # Project.Activate() fails when hidden
                break

        r = await call("insert_subproject", file_path=tmp_mpp)
        ok("18. insert_subproject", r.get("status") == "inserted", str(r))

        try:
            os.remove(tmp_mpp)
        except Exception:
            pass
    except Exception as e:
        ok("18. insert_subproject", False, str(e))

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

    return checks.summary("Export and multi-project")


def test_export_multiproject_live():
    """Run the live scenario; any failed check fails the test."""
    assert asyncio.run(run_tests())


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(run_tests()) else 1)
