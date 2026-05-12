"""Tasks module — CRUD + my-tasks reader for to-do items.

Re-exports the service entry points but NOT the FastAPI router or
Pydantic schemas, so unrelated modules can `from src.app.core.tasks
import create_task` without dragging in HTTP layer deps.
"""
from src.app.core.tasks.models import TaskPriority, TaskStatus
from src.app.core.tasks.service import (
    create_task,
    delete_task,
    get_task,
    list_my_tasks,
    list_tasks_for_entity,
    update_task,
)

__all__ = [
    "TaskPriority",
    "TaskStatus",
    "create_task",
    "delete_task",
    "get_task",
    "list_my_tasks",
    "list_tasks_for_entity",
    "update_task",
]
