"""
Fictional project setup shared by the calendars and rates live scenario tests.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _scenario import call  # noqa: E402


async def setup_project():
    """Create the test project. Returns (uid_alpha, uid_beta, uid_gamma)."""
    # -------------------------------------------------------------------
    # Setup — create a test project
    # -------------------------------------------------------------------
    print("\n=== SETUP ===")

    r = await call("new_project", title="Calendars Rates Test", start="2026-04-01")
    print(f"  Created project: {r.get('title')}")

    tasks_data = json.dumps([
        {"name": "Programme A", "outline_level": 1},
        {"name": "Task Alpha",  "outline_level": 2, "start": "2026-04-01", "duration_days": 10},
        {"name": "Task Beta",   "outline_level": 2, "start": "2026-04-15", "duration_days": 20},
        {"name": "Milestone M", "outline_level": 2, "start": "2026-05-15", "duration_days": 0},
        {"name": "Task Gamma",  "outline_level": 2, "start": "2026-06-01", "duration_days": 30},
    ])
    r = await call("bulk_add_tasks", tasks_json=tasks_data)
    created = r.get("tasks", [])
    uid_alpha = created[1]["unique_id"] if len(created) > 1 else None
    uid_beta  = created[2]["unique_id"] if len(created) > 2 else None
    uid_gamma = created[4]["unique_id"] if len(created) > 4 else None

    # Add a predecessor so we get slack values
    if uid_alpha and uid_beta:
        await call("add_predecessor", successor_unique_id=uid_beta, predecessor_unique_id=uid_alpha, link_type="FS")

    # Add a resource for resource tests
    await call("add_resource", name="PM Lead", max_units=1.0)
    if uid_alpha:
        await call("assign_resource", task_unique_id=uid_alpha, resource_name="PM Lead")

    return uid_alpha, uid_beta, uid_gamma
