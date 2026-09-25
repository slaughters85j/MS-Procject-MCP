"""
Live test of the mpxj_read_* tools: build a fictional project through COM, save it, and check
that what mpxj reads from the saved .mpp matches what Project itself reports.

Needs MS Project, the mpxj extra (pip install -e ".[mpxj]") and a Java runtime (JAVA_HOME);
skipped when mpxj or Java is missing.
"""
import datetime
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.dirname(__file__))

UTC = datetime.timezone.utc  # UTC-aware datetimes reach COM unshifted


@pytest.fixture(scope="module")
def jvm():
    pytest.importorskip("mpxj")
    from src.mpxj_jvm import MpxjNotAvailableError, _ensure_jvm
    try:
        _ensure_jvm()
    except MpxjNotAvailableError as e:
        pytest.skip(f"Java runtime not available: {e}")


def _build_project(app, path):
    """A small fictional refit project with rates, fractional units, a lagged link, a fixed
    cost, a deadline and a calendar exception. Returns what Project reports for it."""
    app.FileNew(SummaryInfo=False)
    proj = app.ActiveProject
    proj.Title = "Crane Refit (fictional)"
    proj.ProjectStart = datetime.datetime(2031, 3, 3, 8, tzinfo=UTC)
    day = int(proj.HoursPerDay * 60)

    welder = proj.Resources.Add("Welder")
    welder.StandardRate = 85.5
    welder.CostPerUse = 25
    inspector = proj.Resources.Add("Inspector")
    inspector.StandardRate = 60

    survey = proj.Tasks.Add("Survey Deck")
    survey.Duration = 2 * day
    survey.FixedCost = 1234.56
    rails = proj.Tasks.Add("Replace Rails")
    rails.Duration = 5 * day
    rails.Priority = 700
    rails.Deadline = datetime.datetime(2031, 3, 21, 17, tzinfo=UTC)
    rails.TaskDependencies.Add(From=survey, Type=1, Lag=day)  # FS + 1 day
    signoff = proj.Tasks.Add("Sign-off")
    signoff.Duration = 0
    signoff.TaskDependencies.Add(From=rails, Type=1, Lag=0)

    survey.Assignments.Add(survey.ID, inspector.ID, 1.0)
    rails.Assignments.Add(rails.ID, welder.ID, 0.5)

    closed = proj.Calendar.Exceptions.Add(1, datetime.datetime(2031, 3, 12, tzinfo=UTC),
                                          datetime.datetime(2031, 3, 12, tzinfo=UTC))
    closed.Name = "Yard Closed"

    app.FileSaveAs(Name=path)
    expected = {
        "tasks": {t.UniqueID: {"name": t.Name, "cost": t.Cost, "start": t.Start.strftime("%Y-%m-%dT%H:%M"),
                               "finish": t.Finish.strftime("%Y-%m-%dT%H:%M")} for t in proj.Tasks},
        "resources": {r.UniqueID: {"name": r.Name, "work_h": r.Work / 60, "cost": r.Cost} for r in proj.Resources},
        "assignments": {(a.TaskUniqueID, a.ResourceUniqueID): {"units": a.Units * 100, "cost": a.Cost,
                                                               "work_h": a.Work / 60}
                        for t in proj.Tasks for a in t.Assignments},
        "uids": {"survey": survey.UniqueID, "rails": rails.UniqueID, "signoff": signoff.UniqueID},
    }
    app.FileCloseEx(0)
    return expected


async def _read(tool, path):
    from server import mcp
    from _toolcall import tool_text
    args = {"file_path": path} if tool == "mpxj_read_project_info" else {"file_path": path, "limit": -1}
    return json.loads(tool_text(await mcp.call_tool(tool, args)))


def test_mpxj_tools_match_project(jvm, project_app, tmp_path):
    import asyncio
    path = str(tmp_path / "crane_refit.mpp")
    expected = _build_project(project_app, path)
    uid = expected["uids"]
    read = {tool: asyncio.run(_read(tool, path)) for tool in (
        "mpxj_read_project_info", "mpxj_read_tasks", "mpxj_read_resources",
        "mpxj_read_assignments", "mpxj_read_calendars")}

    info = read["mpxj_read_project_info"]["project_info"]
    assert info["project_title"] == "Crane Refit (fictional)"
    assert info["schedule_from"] == "START"
    assert (info["task_count"], info["resource_count"], info["assignment_count"]) == (3, 2, 2)

    tasks = {t["unique_id"]: t for t in read["mpxj_read_tasks"]["tasks"]}
    assert set(tasks) == set(expected["tasks"])
    for task_uid, want in expected["tasks"].items():
        got = tasks[task_uid]
        assert got["name"] == want["name"]
        assert got.get("cost", 0) == pytest.approx(want["cost"])  # keeps cents
        assert (got["start"], got["finish"]) == (want["start"], want["finish"])
    rails = tasks[uid["rails"]]
    assert rails["priority"] == 700
    assert rails["deadline"].startswith("2031-03-21")
    link = rails["predecessors"][0]
    assert (link["task_unique_id"], link["task_name"], link["type"]) == (uid["survey"], "Survey Deck", "FS")
    assert link["lag"]["amount"] == 1.0 and link["lag"]["units"] == "d"
    assert tasks[uid["signoff"]]["milestone"] is True

    resources = {r["unique_id"]: r for r in read["mpxj_read_resources"]["resources"]}
    assert set(resources) == set(expected["resources"])
    for res_uid, want in expected["resources"].items():
        got = resources[res_uid]
        assert got["work"] == {"amount": pytest.approx(want["work_h"]), "units": "h"}
        assert got.get("cost", 0) == pytest.approx(want["cost"])
    welder = next(r for r in resources.values() if r["name"] == "Welder")
    assert welder["standard_rate"] == {"amount": 85.5, "units": "h"}

    assignments = {(a["task_unique_id"], a["resource_unique_id"]): a
                   for a in read["mpxj_read_assignments"]["assignments"]}
    assert set(assignments) == set(expected["assignments"])
    for key, want in expected["assignments"].items():
        got = assignments[key]
        assert got["units"] == pytest.approx(want["units"])  # 50, not truncated
        assert got.get("cost", 0) == pytest.approx(want["cost"])
        assert got["work"]["amount"] == pytest.approx(want["work_h"])

    standard = next(c for c in read["mpxj_read_calendars"]["calendars"] if c["name"] == "Standard")
    assert standard["working_hours"]["MONDAY"] == ["08:00-12:00", "13:00-17:00"]
    assert [e["name"] for e in standard["exceptions"]] == ["Yard Closed"]


def test_mpxj_missing_file_is_an_error(jvm, tmp_path):
    import asyncio
    from server import mcp
    result = asyncio.run(mcp.call_tool("mpxj_read_tasks", {"file_path": str(tmp_path / "absent.mpp")}))
    assert result.isError
    body = json.loads(result.content[0].text)
    assert body["error_type"] == "MpxjFileError"
