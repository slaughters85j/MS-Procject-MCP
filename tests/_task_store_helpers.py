"""
Shared mock builders (COM Task, COM Project) for the TaskStore tests.
"""

from unittest.mock import MagicMock


def _make_task(uid, name="Task", task_id=1):
    """Create a mock COM Task object."""
    t = MagicMock()
    t.UniqueID = uid
    t.Name = name
    t.ID = task_id
    return t


def _make_project(tasks=None, resources=None):
    """Create a mock COM Project with Tasks and Resources."""
    proj = MagicMock()
    proj.Tasks = tasks if tasks is not None else []
    proj.Resources = resources if resources is not None else []
    return proj
