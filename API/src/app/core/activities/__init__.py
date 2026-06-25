"""Activities timeline — universal per-entity event log.

`activities.log(...)` is the reusable, non-raising helper any module
imports to record events. The HTTP-facing parts (router, schemas)
stay out of this re-export so other modules don't accidentally pull
in FastAPI / Pydantic by importing `activities`.
"""
from src.app.core.activities.models import ActivityType
from src.app.core.activities.service import (
    create_note,
    list_activities,
    log,
    record_in_session,
)

__all__ = [
    "ActivityType",
    "create_note",
    "list_activities",
    "log",
    "record_in_session",
]
