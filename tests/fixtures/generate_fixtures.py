#!/usr/bin/env python3
"""
Fixture Generator

Creates .mpp fixture files via COM automation on Windows.
Run this ONCE on a Windows machine with MS Project installed:

    python tests/fixtures/generate_fixtures.py

Output goes to tests/fixtures/generated/. These files are gitignored
because .mpp is a binary format that bloats the repo. The integration
test harness (conftest.py) can also self-bootstrap by creating minimal
projects on-the-fly if fixtures are missing.

FIXTURES CREATED:
  basic_project.mpp    — 4 tasks, 1 summary, 1 milestone, RAG tags
  large_project.mpp    — 100+ tasks for performance/stress testing
  multi_resource.mpp   — Tasks with resource assignments
  constrained.mpp      — Tasks with scheduling constraints
  empty_project.mpp    — Blank project (no tasks)
"""

import os
import sys
import datetime


def _check_platform():
    if sys.platform != "win32":
        print("ERROR: This script must run on Windows with MS Project installed.")
        print("       It creates .mpp fixture files via COM automation.")
        sys.exit(1)
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        print("ERROR: pywin32 not installed. Run: pip install pywin32")
        sys.exit(1)


OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "generated")
UTC = datetime.timezone.utc  # UTC-aware datetimes reach COM unshifted (naive ones get the local offset)


def _new_project(app, title):
    """Blank project without the Project Information dialog (FileNew() alone opens it and blocks)."""
    app.FileNew(SummaryInfo=False)
    proj = app.ActiveProject
    proj.Title = title
    return proj, int(proj.HoursPerDay * 60)  # minutes per day; Project has no MinutesPerDay


def _assign(proj, task, *names):
    """Assign resources by name, creating them if needed (list-separator independent)."""
    for name in names:
        res = next((r for r in proj.Resources if r is not None and r.Name == name), None) or proj.Resources.Add(name)
        task.Assignments.Add(task.ID, res.ID, 1.0)


def _ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"Output directory: {OUTPUT_DIR}")


def _save_and_close(app, name):
    """Save as .mpp to OUTPUT_DIR and close."""
    path = os.path.join(OUTPUT_DIR, name)
    app.FileSaveAs(Name=path, Format=0)
    app.FileClose(Save=0)
    print(f"  Created: {name}")
    return path


def create_basic_project(app):
    """4 tasks: 1 summary, 2 work tasks with RAG, 1 milestone."""
    print("Creating basic_project.mpp...")
    proj, mpd = _new_project(app, "Basic Fixture")

    t1 = proj.Tasks.Add("Summary Phase")
    t1.OutlineLevel = 1

    t2 = proj.Tasks.Add("Task Alpha")
    t2.OutlineLevel = 2
    t2.Duration = mpd * 3
    t2.Text1 = "Green"
    t2.Notes = "This is task Alpha for integration testing."

    t3 = proj.Tasks.Add("Task Beta")
    t3.OutlineLevel = 2
    t3.Duration = mpd * 5
    t3.Text1 = "Red"
    t3.Predecessors = str(t2.ID)

    t4 = proj.Tasks.Add("Milestone Done")
    t4.OutlineLevel = 2
    t4.Duration = 0
    t4.Milestone = True
    t4.Predecessors = str(t3.ID)

    _save_and_close(app, "basic_project.mpp")


def create_large_project(app):
    """100+ tasks for performance and stress testing."""
    print("Creating large_project.mpp...")
    proj, mpd = _new_project(app, "Large Fixture")

    # Suppress calc during bulk add
    app.Calculation = 0  # pjManual (PjCalculation: pjAutomatic=-1, pjManual=0)

    for phase in range(1, 6):
        summary = proj.Tasks.Add(f"Phase {phase}")
        summary.OutlineLevel = 1
        for task_num in range(1, 21):
            t = proj.Tasks.Add(f"P{phase}-Task-{task_num:02d}")
            t.OutlineLevel = 2
            t.Duration = mpd * (task_num % 5 + 1)
            rag = ["Green", "Amber", "Red"][task_num % 3]
            t.Text1 = rag

    # Restore auto-calc and recalculate
    app.Calculation = -1  # pjAutomatic
    app.CalculateAll()

    _save_and_close(app, "large_project.mpp")


def create_multi_resource(app):
    """Tasks with resource assignments for TaskStore tests."""
    print("Creating multi_resource.mpp...")
    proj, mpd = _new_project(app, "Resource Fixture")

    t1 = proj.Tasks.Add("Design Review")
    t1.Duration = mpd * 2
    _assign(proj, t1, "Alice")

    t2 = proj.Tasks.Add("Implementation")
    t2.Duration = mpd * 10
    _assign(proj, t2, "Bob", "Charlie")

    t3 = proj.Tasks.Add("Testing")
    t3.Duration = mpd * 3
    _assign(proj, t3, "Alice", "Bob")
    t3.Predecessors = str(t2.ID)

    _save_and_close(app, "multi_resource.mpp")


def create_constrained(app):
    """Tasks with scheduling constraints for verify_write tests."""
    print("Creating constrained.mpp...")
    proj, mpd = _new_project(app, "Constrained Fixture")

    t1 = proj.Tasks.Add("SNET Task")
    t1.Duration = mpd * 3
    t1.ConstraintType = 4  # SNET
    t1.ConstraintDate = datetime.datetime(2026, 6, 1, 8, tzinfo=UTC)

    t2 = proj.Tasks.Add("FNLT Task")
    t2.Duration = mpd * 2
    t2.ConstraintType = 7  # FNLT
    t2.ConstraintDate = datetime.datetime(2026, 7, 15, 17, tzinfo=UTC)

    t3 = proj.Tasks.Add("MSO Task")
    t3.Duration = mpd * 1
    t3.ConstraintType = 2  # pjMSO (Must Start On); 3 is pjMFO
    t3.ConstraintDate = datetime.datetime(2026, 8, 3, 8, tzinfo=UTC)

    _save_and_close(app, "constrained.mpp")


def create_empty_project(app):
    """Blank project with no tasks."""
    print("Creating empty_project.mpp...")
    _new_project(app, "Empty Fixture")
    _save_and_close(app, "empty_project.mpp")


def main():
    _check_platform()
    _ensure_output_dir()

    import win32com.client
    import pythoncom

    pythoncom.CoInitialize()

    print("Launching MS Project...")
    # DispatchEx starts a private instance: Dispatch would attach to (then hide and quit) a running one.
    app = win32com.client.DispatchEx("MSProject.Application")
    app.Visible = False
    app.DisplayAlerts = False

    try:
        create_basic_project(app)
        create_large_project(app)
        create_multi_resource(app)
        create_constrained(app)
        create_empty_project(app)
        print(f"\nAll fixtures created in {OUTPUT_DIR}")
    finally:
        try:
            app.Quit(0)
        except Exception:
            pass
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
