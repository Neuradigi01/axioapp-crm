"""Staff module — sales-specific user profile + attendance.

Re-exports service entry points (no FastAPI / Pydantic) so other
modules can `from src.app.core.staff import compute_performance`
without dragging in HTTP-layer deps.
"""
from src.app.core.staff.service import (
    clock_in,
    clock_out,
    compute_performance,
    get_profile,
    list_activities_for,
    list_attendance,
    list_staff,
    upsert_profile,
)

__all__ = [
    "clock_in",
    "clock_out",
    "compute_performance",
    "get_profile",
    "list_activities_for",
    "list_attendance",
    "list_staff",
    "upsert_profile",
]
