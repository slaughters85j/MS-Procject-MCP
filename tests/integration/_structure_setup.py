"""
Fictional project setup shared by the structure and export live scenario tests.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _scenario import call  # noqa: E402


async def setup_project():
    """Create the test project. Returns (main_project_name, uid)."""
    # -----------------------------------------------------------------------
    # Setup
    # -----------------------------------------------------------------------
    print("\n=== SETUP ===")

    r = await call("new_project", title="Structure Export Test", start="2026-04-01")
    main_project_name = r.get("name", "Structure Export Test")
    print(f"  Created project: {r.get('title')}")

    # Add tasks: 2 programmes with children + milestones
    tasks_data = json.dumps([
        {"name": "Programme Alpha", "outline_level": 1},
        {"name": "Task A", "outline_level": 2, "start": "2026-04-01", "duration_days": 10},
        {"name": "Task B", "outline_level": 2, "start": "2026-04-15", "duration_days": 10},
        {"name": "Milestone X", "outline_level": 2, "milestone": True, "start": "2026-04-30"},
        {"name": "Programme Beta", "outline_level": 1},
        {"name": "Task C", "outline_level": 2, "start": "2026-05-01", "duration_days": 15},
        {"name": "Task D", "outline_level": 2, "start": "2026-05-20", "duration_days": 10},
        {"name": "Sub-task D1", "outline_level": 3, "start": "2026-05-20", "duration_days": 5},
        {"name": "Sub-task D2", "outline_level": 3, "start": "2026-05-27", "duration_days": 5},
        {"name": "Milestone Y", "outline_level": 2, "milestone": True, "start": "2026-06-15"},
    ])
    r = await call("bulk_add_tasks", tasks_json=tasks_data)
    created = r.get("tasks", [])
    uid = {t["name"]: t["unique_id"] for t in created}
    print(f"  Created {len(created)} tasks")

    # Add resources
    for name in ["Alice", "Bob", "Charlie"]:
        await call("add_resource", name=name)
    print("  Added 3 resources")

    # Assign resources
    await call("assign_resource", task_unique_id=uid["Task A"], resource_name="Alice")
    await call("assign_resource", task_unique_id=uid["Task B"], resource_name="Bob")
    await call("assign_resource", task_unique_id=uid["Task C"], resource_name="Charlie")
    await call("assign_resource", task_unique_id=uid["Task D"], resource_name="Alice")
    print("  Assigned 4 resources")

    # Add predecessor chain: A → B → C → D
    links = json.dumps([
        {"successor_unique_id": uid["Task B"], "predecessor_unique_id": uid["Task A"]},
        {"successor_unique_id": uid["Task C"], "predecessor_unique_id": uid["Task B"]},
        {"successor_unique_id": uid["Task D"], "predecessor_unique_id": uid["Task C"]},
    ])
    await call("bulk_add_predecessors", links_json=links)
    print("  Created 3 predecessor links")

    # Set RAG
    rag_updates = json.dumps([
        {"unique_id": uid["Task A"], "rag": "Green"},
        {"unique_id": uid["Task B"], "rag": "Amber"},
        {"unique_id": uid["Task C"], "rag": "Red"},
    ])
    await call("bulk_update_rag", updates=rag_updates)
    print("  Set RAG statuses")

    # Save baseline 0
    await call("save_baseline", baseline_number=0)
    print("  Saved baseline 0")

    # Shift Task B finish to create variance
    await call("update_task", unique_id=uid["Task B"], finish="2026-05-05")
    print("  Shifted Task B finish for variance test")

    return main_project_name, uid
