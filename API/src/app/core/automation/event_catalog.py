"""Event-type discovery catalog for the trigger editor.

The Step-8 trigger editor renders an event picker; this module
exposes the canonical list of CRM domain events the dispatcher
recognises plus a one-line description and a sample payload shape
so the editor can show variable hints without hitting the running
publishers.

Each entry maps an ``event_type`` string to:

* ``label`` — human-readable name (Title Case).
* ``description`` — one sentence the editor surfaces under the
  picker.
* ``sample_payload`` — a representative envelope shape. Operators
  pull dot-paths from this when authoring conditions or custom
  recipient resolvers.

Adding a new event:

1. Pick a string key in ``<domain>.<verb>`` shape (matches
   :mod:`core.events.bus`).
2. Add a ``CatalogEntry`` here.
3. The emit call lands in the matching step (5 / 6 / 10 / 11 / 12).

The catalog is the **contract** between publishers and the
automation engine. Step 5+ will add a pin-test
(``test_event_catalog_consistency.py``) that fails CI when a real
``bus.publish`` call uses an event type missing from the catalog.

The full taxonomy lives in ``core.events.bus`` module docstring;
this module exposes the subset that automation triggers can
actually subscribe to today (Step 5/6 ship `user.signed_up` +
`lead.created`; later steps add appointments / quotes / invoices /
birthdays / stale-lead).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One row in the discovery catalog."""

    event_type: str
    label: str
    description: str
    sample_payload: dict[str, Any]


_CATALOG: dict[str, CatalogEntry] = {}


def _register(entry: CatalogEntry) -> None:
    _CATALOG[entry.event_type] = entry


# --- Auth + onboarding -----------------------------------------------


_register(
    CatalogEntry(
        event_type="user.signed_up",
        label="User signed up",
        description="A new Owner finishes the self-signup flow.",
        sample_payload={
            # Step 5 publisher emits this shape verbatim — keep
            # in sync. The flat `user_id` lives at the top level
            # so `recipient_resolver='user.email'` works without
            # additional config; the nested `user` dict carries
            # the variable values the seeded "User Welcome"
            # template's body references (``{{ user.full_name }}``).
            "user_id": "00000000-0000-0000-0000-000000000000",
            "user": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
            "signed_up_at": "2026-06-29T12:30:00+00:00",
        },
    )
)
_register(
    CatalogEntry(
        event_type="user.invited",
        label="Team member invited",
        description="An operator invites a new team member (invite email queued).",
        sample_payload={
            "user": {"email": "invitee@example.com"},
            "invited_by_user_id": "00000000-0000-0000-0000-000000000000",
        },
    )
)
_register(
    CatalogEntry(
        event_type="user.invitation_accepted",
        label="Invitation accepted",
        description="An invited user finishes signup.",
        sample_payload={
            "user": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Rahul Patel",
                "email": "rahul@example.com",
            },
        },
    )
)


# --- Leads + contacts -----------------------------------------------


_register(
    CatalogEntry(
        event_type="lead.created",
        label="Lead created",
        description=(
            "A new lead lands from ANY source — form widget, "
            "Google Ads, Meta Ads, CSV import, manual entry, "
            "WhatsApp inbound, walk-in, API."
        ),
        sample_payload={
            "lead": {
                "id": "00000000-0000-0000-0000-000000000000",
                "source": "website",
                "estimated_value": 45000,
                "owner_user_id": None,
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "first_name": "Asha",
                "email": "asha@example.com",
                "phone": "+919876543210",
            },
            "contact_id": "00000000-0000-0000-0000-000000000000",
        },
    )
)
_register(
    CatalogEntry(
        event_type="lead.status_changed",
        label="Lead status changed",
        description="The lead transitions between pipeline stages.",
        sample_payload={
            "lead": {"id": "00000000-0000-0000-0000-000000000000"},
            "from_status": "new",
            "to_status": "qualified",
            "contact": {"first_name": "Asha"},
        },
    )
)
_register(
    CatalogEntry(
        event_type="lead.score_threshold",
        label="Lead score crossed threshold",
        description="Lead score crosses a configured threshold (e.g. ≥75).",
        sample_payload={
            "lead": {"id": "00000000-0000-0000-0000-000000000000", "score": 75},
            "threshold": 75,
            "direction": "up",
            "contact": {"first_name": "Asha"},
        },
    )
)
_register(
    CatalogEntry(
        event_type="contact.birthday",
        label="Contact birthday",
        description="The daily sweep finds a contact whose birthday is today.",
        sample_payload={
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "first_name": "Asha",
                "birthday": "2026-06-26",
            }
        },
    )
)


# --- Appointments ----------------------------------------------------


_register(
    CatalogEntry(
        event_type="appointment.booked",
        label="Appointment booked",
        description="A new appointment is scheduled.",
        sample_payload={
            "appointment": {
                "id": "00000000-0000-0000-0000-000000000000",
                "scheduled_at": "2026-07-01T10:00:00+05:30",
                "location": "Bengaluru Showroom",
            },
            "contact": {"first_name": "Asha"},
        },
    )
)
_register(
    CatalogEntry(
        event_type="appointment.reminder_24h",
        label="Appointment reminder (24h)",
        description="Daily sweep fires 24 hours before scheduled time.",
        sample_payload={
            "appointment": {"scheduled_at": "2026-07-01T10:00:00+05:30"},
            "contact": {"first_name": "Asha"},
        },
    )
)
_register(
    CatalogEntry(
        event_type="appointment.reminder_1h",
        label="Appointment reminder (1h)",
        description="Hourly sweep fires 1 hour before scheduled time.",
        sample_payload={
            "appointment": {"scheduled_at": "2026-07-01T10:00:00+05:30"},
            "contact": {"first_name": "Asha"},
        },
    )
)


# --- Sales ----------------------------------------------------------


_register(
    CatalogEntry(
        event_type="quote.sent",
        label="Quote sent",
        description="A quote is sent to a contact.",
        sample_payload={
            "quote": {
                "id": "00000000-0000-0000-0000-000000000000",
                "total_amount": 45000,
                "currency": "INR",
            },
            "contact": {"first_name": "Asha"},
        },
    )
)
_register(
    CatalogEntry(
        event_type="quote.accepted",
        label="Quote accepted",
        description="The contact accepts the quote.",
        sample_payload={
            "quote": {"id": "00000000-0000-0000-0000-000000000000", "total_amount": 45000},
            "contact": {"first_name": "Asha"},
        },
    )
)
_register(
    CatalogEntry(
        event_type="invoice.sent",
        label="Invoice sent",
        description="An invoice is sent to a contact.",
        sample_payload={
            "invoice": {"id": "INV-2026-0421", "total_amount": 45000},
            "contact": {"first_name": "Asha"},
        },
    )
)
_register(
    CatalogEntry(
        event_type="invoice.overdue_7d",
        label="Invoice overdue (7d)",
        description="Daily sweep finds invoices 7 days past due.",
        sample_payload={
            "invoice": {"id": "INV-2026-0421", "due_date": "2026-06-19"},
            "contact": {"first_name": "Asha"},
        },
    )
)


# --- Public API -----------------------------------------------------


def list_catalog() -> list[CatalogEntry]:
    """Returns every catalog entry. Stable ordering by ``event_type``
    so the editor's picker renders deterministically."""
    return sorted(_CATALOG.values(), key=lambda e: e.event_type)


def get_entry(event_type: str) -> CatalogEntry | None:
    """One-row lookup. ``None`` when the event type isn't in the
    catalog — the router maps to 404."""
    return _CATALOG.get(event_type)


def is_known(event_type: str) -> bool:
    """Pin-test helper — the Step-5 consistency test calls this from
    every publisher's emit site."""
    return event_type in _CATALOG


__all__ = [
    "CatalogEntry",
    "get_entry",
    "is_known",
    "list_catalog",
]
