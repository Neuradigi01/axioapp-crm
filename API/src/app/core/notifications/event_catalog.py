"""Central registry of user-facing notification event types.

Each entry describes ONE event that can trigger a user notification via
``notify()``. The Settings → Notifications preferences UI reads this
catalog to render its full type list; new entries surface immediately
without any frontend change.

Add a new entry here whenever you introduce a new ``notify(type="...")``
call site. Do NOT include automation / workflow event codes — those
live in ``core/automation/event_catalog.py`` and are a different
concept (they drive user-authored workflows, not the bell / email
delivery system).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationEventEntry:
    event_type: str
    label: str
    description: str
    group: str


CATALOG: list[NotificationEventEntry] = [
    # --- Appointments -----------------------------------------------------
    NotificationEventEntry(
        event_type="appointment.assigned",
        label="New appointment assigned to me",
        description="A new appointment was scheduled with you as the assigned owner.",
        group="Appointments",
    ),
    NotificationEventEntry(
        event_type="appointment.rescheduled",
        label="Appointment I own was rescheduled",
        description="An appointment you own was moved to a new time.",
        group="Appointments",
    ),
    NotificationEventEntry(
        event_type="appointment.cancelled",
        label="Appointment I own was cancelled",
        description="An appointment you own was cancelled.",
        group="Appointments",
    ),
    NotificationEventEntry(
        event_type="appointment.completed",
        label="Appointment I own was marked complete",
        description="An appointment you own was marked complete.",
        group="Appointments",
    ),
    # --- Tasks ------------------------------------------------------------
    NotificationEventEntry(
        event_type="task.assigned",
        label="New task assigned to me",
        description="A task was assigned to you.",
        group="Tasks",
    ),
    NotificationEventEntry(
        event_type="task.completed",
        label="Task I own was completed",
        description="A task you own was marked complete.",
        group="Tasks",
    ),
    # --- Messages ---------------------------------------------------------
    NotificationEventEntry(
        event_type="conversation.message",
        label="New message in a conversation I own",
        description="A new incoming message arrived in a conversation assigned to you.",
        group="Messages",
    ),
    NotificationEventEntry(
        event_type="conversation.mention",
        label="I was mentioned in a note",
        description="Someone @-mentioned you in an internal conversation note.",
        group="Messages",
    ),
    # --- Templates --------------------------------------------------------
    NotificationEventEntry(
        event_type="templates.external_status_changed",
        label="WhatsApp template status changed",
        description=(
            "A WhatsApp Business template you own was approved, rejected, "
            "or paused by Meta."
        ),
        group="Templates",
    ),
]
