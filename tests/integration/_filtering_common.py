"""
Shared pieces of the live filtering scenario tests: the tool-call helper, the fictional test
project (hierarchy, resources, links, RAG) and the summary/cleanup step.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.dirname(__file__))
from server import mcp  # noqa: E402
from _toolcall import tool_text  # noqa: E402


async def call(name, args=None):
    """Call an MCP tool and return parsed JSON or raw text."""
    text = tool_text(await mcp.call_tool(name, args or {}))
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


async def setup_project():
    """Create the fictional test project. Returns (project name, {task name: UniqueID})."""
    task_uids = {}
    print("=== Setup: new_project ===")
    r = await call("new_project", {"title": "Filtering Test", "start": "2026-04-01"})
    main_project_name = r["name"]  # Actual name (e.g. "Project1")
    print(f"  Project: {main_project_name}")

    print("=== Setup: bulk_add_tasks ===")
    tasks = [
        {"name": "Programme Alpha", "outline_level": 1},
        {"name": "Design Work", "outline_level": 2, "start": "2026-04-01", "finish": "2026-05-01", "duration_days": 22},
        {"name": "Build Work", "outline_level": 2, "start": "2026-05-02", "finish": "2026-06-30", "duration_days": 43},
        {"name": "Testing", "outline_level": 3, "start": "2026-06-01", "finish": "2026-06-20", "duration_days": 15},
        {"name": "Go-Live Milestone", "outline_level": 2, "milestone": True, "start": "2026-06-30"},
        {"name": "Programme Beta", "outline_level": 1},
        {"name": "Planning", "outline_level": 2, "start": "2026-04-01", "finish": "2026-04-15", "duration_days": 11},
        {"name": "Execution", "outline_level": 2, "start": "2026-04-16", "finish": "2026-07-31", "duration_days": 77},
    ]
    r = await call("bulk_add_tasks", {"tasks_json": json.dumps(tasks)})
    print(f"  Created: {r['created']} tasks")
    task_uids = {t["name"]: t["unique_id"] for t in r["tasks"]}

    # Add resources
    print("=== Setup: add_resource ===")
    await call("add_resource", {"name": "Alice", "type": 0, "max_units": 1.0})
    await call("add_resource", {"name": "Bob", "type": 0, "max_units": 1.0})
    print("  Resources: Alice, Bob")

    # Assign resources
    print("=== Setup: assign_resource ===")
    await call("assign_resource", {"task_unique_id": task_uids["Design Work"], "resource_name": "Alice"})
    await call("assign_resource", {"task_unique_id": task_uids["Build Work"], "resource_name": "Alice"})
    await call("assign_resource", {"task_unique_id": task_uids["Testing"], "resource_name": "Bob"})
    print("  Assignments: Alice->Design+Build, Bob->Testing")

    # Add predecessor links
    print("=== Setup: bulk_add_predecessors ===")
    links = [
        {"successor_unique_id": task_uids["Build Work"], "predecessor_unique_id": task_uids["Design Work"], "link_type": "FS"},
        {"successor_unique_id": task_uids["Go-Live Milestone"], "predecessor_unique_id": task_uids["Build Work"], "link_type": "FS"},
        {"successor_unique_id": task_uids["Execution"], "predecessor_unique_id": task_uids["Planning"], "link_type": "FS"},
    ]
    await call("bulk_add_predecessors", {"links_json": json.dumps(links)})
    print("  Links: 3 added")

    # Set RAG on some tasks
    print("=== Setup: bulk_update_rag ===")
    rag_updates = [
        {"unique_id": task_uids["Design Work"], "rag": "Green"},
        {"unique_id": task_uids["Build Work"], "rag": "Amber"},
        {"unique_id": task_uids["Testing"], "rag": "Red"},
        {"unique_id": task_uids["Planning"], "rag": "Green"},
    ]
    await call("bulk_update_rag", {"updates": json.dumps(rag_updates)})
    print("  RAG set on 4 tasks")

    return main_project_name, task_uids


async def finish(results, title):
    """Print the pass/fail summary, close every test project, and return True if all passed."""
    print("\n" + "=" * 50)
    print(title)
    print("=" * 50)
    passed = failed = 0
    for name, status in results.items():
        print(f"  [{status:4s}] {name}")
        if status == "PASS":
            passed += 1
        else:
            failed += 1
    print(f"\n  {passed} passed, {failed} failed / {len(results)} total")

    # Cleanup: close all test projects
    print("\nCleaning up...")
    # Close projects in reverse order to avoid index shifts
    for _ in range(5):  # max 5 attempts
        try:
            r = await call("list_projects")
            if r["count"] == 0:
                break
            await call("close_project", {"save": False})
            print(f"  Closed a project ({r['count']-1} remaining)")
        except Exception:
            break
    print("Cleanup complete.")

    return failed == 0
