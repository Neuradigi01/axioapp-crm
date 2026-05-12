"""Appointments module — scheduled meetings between staff and contacts.

Re-exports the service entry points (no FastAPI / Pydantic) so other
modules — most notably the Phase 4 field-visit module — can import
`from src.app.core.appointments import find_conflicts, create_appointment`
and reuse this engine without dragging in HTTP-layer deps.
"""
from src.app.core.appointments.models import AppointmentStatus
from src.app.core.appointments.service import (
    create_appointment,
    delete_appointment,
    find_conflicts,
    get_appointment,
    list_appointments,
    update_appointment,
)

__all__ = [
    "AppointmentStatus",
    "create_appointment",
    "delete_appointment",
    "find_conflicts",
    "get_appointment",
    "list_appointments",
    "update_appointment",
]
