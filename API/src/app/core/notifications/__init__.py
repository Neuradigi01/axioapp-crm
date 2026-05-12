"""Notifications module — real-time in-app messaging.

Re-exports the `notify(...)` helper (and channel enum) so other modules
can import `from src.app.core.notifications import notify` without
dragging in FastAPI / Pydantic. Same pattern as audit / activities.
"""
from src.app.core.notifications.models import NotificationChannel
from src.app.core.notifications.service import (
    get_preferences,
    list_for_user,
    mark_all_read,
    mark_read,
    notify,
    update_preferences,
)

__all__ = [
    "NotificationChannel",
    "get_preferences",
    "list_for_user",
    "mark_all_read",
    "mark_read",
    "notify",
    "update_preferences",
]
