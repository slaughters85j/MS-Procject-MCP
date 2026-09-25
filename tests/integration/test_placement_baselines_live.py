"""
Live tests for task placement, targeted baselines, rescheduling, cost/earned-value numbers,
read-only tools leaving the file clean, cross-file links and the XML round trip.

Requires MS Project on Windows; skipped otherwise by tests/integration/conftest.py.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.dirname(__file__))
from server import mcp  # noqa: E402
from _toolcall import tool_text  # noqa: E402
from src.project_session import get_session  # noqa: E402

PLAN = [
    {"name": "Phase One", "outline_level": 1},
    {"name": "Design", "outline_level": 2, "start": "2031-03-03", "duration_days": 5, "manual": False},
    {"name": "Build", "outline_level": 2, "duration_days": 10, "manual": False},
    {"name": "Phase Two", "outline_level": 1},
    {"name": "Test", "outline_level": 2, "duration_days": 5, "manual": False},
    {"name": "Ship", "outline_level": 2, "duration_days": 0, "milestone": True, "manual": False},
    {"name": "Loose End", "outline_level": 1, "duration_days": 2, "manual": False},
]
READ_ONLY_TOOLS = [
    ("get_cost_summary", {}), ("get_earned_value", {}), ("find_available_slack", {"min_days": 0}),
    ("get_schedule_analysis", {}), ("get_critical_path", {}), ("get_critical_path_sequence", {}),
    ("get_progress_summary", {}), ("validate_schedule", {}), ("get_milestone_report", {}),
    ("get_tasks", {"limit": -1}), ("get_resources", {}), ("get_resource_workload", {"resource_name": "Engineer"}),
    ("get_constraints", {}), ("get_wbs_structure", {}), ("get_actual_work", {}),
]


async def call(tool, **kwargs):
    text = tool_text(await mcp.call_tool(tool, kwargs))
    try:
        return json.loads(text)
    except ValueError:
        return text


def by_name(proj, name):
    return [t for t in proj.Tasks if t is not None and t.Name == name]


async def build_plan(path):
    await call("new_project", title="Alpha", start="2031-03-03")
    r = await call("bulk_add_tasks", tasks_json=json.dumps(PLAN))
    uid = {t["name"]: t["unique_id"] for t in r["tasks"]}
    for succ, pred in (("Build", "Design"), ("Test", "Build"), ("Ship", "Test")):
        await call("add_predecessor", successor_unique_id=uid[succ], predecessor_unique_id=uid[pred])
    await call("save_project_as", file_path=path)
    return uid, get_session().app


def test_move_and_copy_keep_structure(tmp_path):
    async def run():
        uid, app = await build_plan(str(tmp_path / "alpha.mpp"))
        proj = app.ActiveProject
        # A user sort and a collapsed outline must not redirect the operation.
        app.Sort(Key1="Name", Ascending1=False, Renumber=False)
        app.OutlineHideSubTasks()
        r = await call("move_task", unique_id=uid["Phase One"], after_unique_id=uid["Ship"])
        assert r["status"] == "moved" and len(r["uid_map"]) == 3
        phase_one = by_name(proj, "Phase One")[0]
        assert phase_one.UniqueID == r["unique_id"] and phase_one.OutlineLevel == 1
        assert [t.OutlineLevel for t in by_name(proj, "Design") + by_name(proj, "Build")] == [2, 2]
        assert by_name(proj, "Build")[0].Predecessors == str(by_name(proj, "Design")[0].ID)

        r = await call("move_task", unique_id=by_name(proj, "Loose End")[0].UniqueID,
                       after_unique_id=by_name(proj, "Test")[0].UniqueID, keep_outline_level=False)
        assert by_name(proj, "Loose End")[0].OutlineLevel == 2

        before = proj.Tasks.Count
        r = await call("copy_task_structure", source_unique_id=by_name(proj, "Phase One")[0].UniqueID)
        assert [t["name"] for t in r["copied_tasks"][0]] == ["Phase One", "Design", "Build"]
        assert proj.Tasks.Count == before + 3
    asyncio.run(run())


def test_targeted_baselines(tmp_path):
    async def run():
        uid, app = await build_plan(str(tmp_path / "alpha.mpp"))
        proj = app.ActiveProject
        r = await call("save_baseline", baseline_number=2, all_tasks=False)
        assert "error" in r  # never "whatever is selected"
        picked = [uid["Design"], uid["Ship"]]
        r = await call("save_baseline", baseline_number=2, unique_ids=picked)
        assert r["tasks_baselined"] == 2
        baselined = sorted(t.UniqueID for t in proj.Tasks if t is not None and str(t.Baseline2Start) != "NA")
        assert baselined == sorted(picked)
        await call("clear_baseline", baseline_number=2, unique_ids=[uid["Ship"]])
        assert [t.UniqueID for t in proj.Tasks if t is not None and str(t.Baseline2Start) != "NA"] == [uid["Design"]]
    asyncio.run(run())


def test_reschedule_cost_and_earned_value(tmp_path):
    async def run():
        uid, app = await build_plan(str(tmp_path / "alpha.mpp"))
        proj = app.ActiveProject
        await call("add_resource", name="Engineer", standard_rate="100/h")
        await call("assign_resource", task_unique_id=uid["Design"], resource_name="Engineer")
        await call("save_baseline", baseline_number=0)
        await call("update_task", unique_id=uid["Design"], percent_complete=50)
        await call("set_project_properties", properties_json=json.dumps({"status_date": "2031-03-05"}))

        cost = await call("get_cost_summary")
        assert cost["totals"]["cost"] == 4000.0 and cost["totals"]["actual_cost"] == 2000.0  # 5d x 8h x $100
        assert cost["by_resource"] == [{"name": "Engineer", "cost": 4000.0, "actual_cost": 2000.0}]
        ev = (await call("get_earned_value"))["project_totals"]
        assert (ev["bcws"], ev["bcwp"], ev["acwp"], ev["spi"]) == (2400.0, 2000.0, 2000.0, 0.833)

        # Every read-only tool must leave a saved project saved.
        await call("save_project")
        for tool, args in READ_ONLY_TOOLS:
            r = await call(tool, **args)
            assert not (isinstance(r, dict) and r.get("error")), (tool, r)
            assert proj.Saved, f"{tool} marked the project unsaved"

        finish = proj.ProjectFinish
        r = await call("what_if_delay", unique_id=uid["Design"], delay_days=3)
        assert r["project_impact"]["estimated_new_finish"] == str(app.DateAdd(finish, 3 * 480))[:10]
        assert proj.ProjectFinish == finish and proj.Saved

        build = by_name(proj, "Build")[0]
        await call("update_task", unique_id=uid["Build"], percent_complete=40)
        await call("reschedule_incomplete_work", reschedule_from="2031-04-14")
        assert build.PercentComplete == 40 and str(build.Resume)[:10] >= "2031-04-15"
    asyncio.run(run())


def test_cross_file_link_and_xml_round_trip(tmp_path):
    async def run():
        uid, app = await build_plan(str(tmp_path / "alpha.mpp"))
        await call("new_project", title="Bravo", start="2031-03-03")
        integrate = (await call("add_task", name="Integrate", duration_days=3))["unique_id"]
        await call("save_project_as", file_path=str(tmp_path / "bravo.mpp"))
        r = await call("cross_project_link", source_project="alpha.mpp", source_unique_id=uid["Ship"],
                       target_project="bravo.mpp", target_unique_id=integrate)
        assert r["target"]["project"] == "bravo.mpp"
        bravo, alpha = app.Projects("bravo.mpp"), app.Projects("alpha.mpp")
        target = [t for t in bravo.Tasks if t is not None and t.UniqueID == integrate][0]
        assert target.Predecessors.startswith(str(tmp_path / "alpha.mpp"))
        assert "bravo.mpp" in by_name(alpha, "Ship")[0].Successors

        await call("switch_project", name_or_index="alpha.mpp")
        xml = str(tmp_path / "alpha.xml")
        r = await call("export_xml", output_path=xml)
        assert r["active_project"].endswith("alpha.mpp") and open(xml, "rb").read(5) == b"<?xml"
        r = await call("import_xml", file_path=xml)
        assert r["task_count"] == len(PLAN)
    asyncio.run(run())
