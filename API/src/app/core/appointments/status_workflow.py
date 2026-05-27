"""Appointment status state-machine. Keep transitions explicit.

Values match `AppointmentStatus` in `core/appointments/models.py`:

    scheduled → completed, no_show, cancelled    (normal lifecycle)
    completed → (terminal)
    no_show   → scheduled                        (rebook after no-show)
    cancelled → scheduled                        (rebook after cancel)

`completed` is intentionally terminal: once an appointment is recorded
as done it doesn't get re-opened — a returning visit is a NEW
appointment row, which keeps reporting per-visit clean. Both
`no_show` and `cancelled` allow `→ scheduled` because the showroom
flow legitimately rebooks after a missed slot.

Service-level enforcement in `update_appointment` rejects any status
change that doesn't appear in this map (identity transitions, e.g.
`scheduled → scheduled`, are also rejected — a no-op should not be a
PATCH).
"""
from __future__ import annotations


ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "scheduled": frozenset({"completed", "no_show", "cancelled"}),
    "completed": frozenset(),
    "no_show": frozenset({"scheduled"}),
    "cancelled": frozenset({"scheduled"}),
}
