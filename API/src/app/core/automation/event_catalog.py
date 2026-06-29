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
            "A new lead lands from ANY source — manual entry / API, "
            "embed widget, Google Ads webhook, Meta Ads webhook, "
            "CSV bulk import. Every source goes through "
            "``core.leads.service.create_lead`` so a single publish "
            "call at the chokepoint covers them all."
        ),
        sample_payload={
            # Flat top-level keys so condition AST paths like
            # `field='source'` work without nesting. Snapshots below
            # carry the variable renderer's lookups.
            "lead_id": "00000000-0000-0000-0000-000000000000",
            "contact_id": "00000000-0000-0000-0000-000000000000",
            "source": "widget",
            "created_at": "2026-06-29T13:00:00+00:00",
            "lead": {
                "id": "00000000-0000-0000-0000-000000000000",
                "source": "widget",
                "status": "active",
                "pipeline_stage": "new",
                "assigned_to_id": None,
                "budget": None,
                "attribution": {"utm_source": "google"},
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
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
        description=(
            "Daily Celery beat sweep finds contacts whose "
            "``date_of_birth`` matches today (month + day) in the "
            "org's timezone. ``event_id=contact_birthday:{contact_id}:{year}`` "
            "deduplicates intraday replays + ensures one fire per "
            "contact per year."
        ),
        sample_payload={
            "contact_id": "00000000-0000-0000-0000-000000000000",
            "age_turning": 35,
            "date_of_birth": "1991-06-29",
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
                "date_of_birth": "1991-06-29",
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
    )
)
_register(
    CatalogEntry(
        event_type="lead.stale_30d",
        label="Lead has been stale for 30 days",
        description=(
            "Daily Celery beat sweep finds leads with no activity in "
            "the last 30 days whose status is not ``won`` / ``lost``. "
            "``event_id=lead_stale_30d:{lead_id}:{first_stale_date}`` "
            "uses the first-stale date so daily re-scans don't refire "
            "until the lead becomes active again."
        ),
        sample_payload={
            "lead_id": "00000000-0000-0000-0000-000000000000",
            "contact_id": "00000000-0000-0000-0000-000000000000",
            "days_since_last_activity": 31,
            "last_activity_at": "2026-05-29T10:00:00+00:00",
            "lead": {
                "id": "00000000-0000-0000-0000-000000000000",
                "status": "active",
                "pipeline_stage": "qualified",
                "assigned_to_id": "00000000-0000-0000-0000-000000000000",
                "last_activity_at": "2026-05-29T10:00:00+00:00",
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
    )
)


# --- Appointments ----------------------------------------------------


_register(
    CatalogEntry(
        event_type="appointment.booked",
        label="Appointment booked",
        description=(
            "A new appointment is scheduled. Fires once at "
            "``core.appointments.service.create_appointment`` after "
            "commit; ``event_id=appointment_booked:{id}`` deduplicates "
            "replays."
        ),
        sample_payload={
            # Flat top-level keys so condition AST paths like
            # `field='location'` work without nesting; the nested
            # `appointment` / `contact` / `org` dicts carry the
            # template renderer's variable lookups.
            "appointment_id": "00000000-0000-0000-0000-000000000000",
            "contact_id": "00000000-0000-0000-0000-000000000000",
            "scheduled_at": "2026-07-01T10:00:00+05:30",
            "location": "Bengaluru Showroom",
            "appointment": {
                "id": "00000000-0000-0000-0000-000000000000",
                "title": "Showroom walk-through",
                "purpose": "showroom_visit",
                "scheduled_at": "2026-07-01T10:00:00+05:30",
                "duration_min": 60,
                "location": "Bengaluru Showroom",
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
    )
)
_register(
    CatalogEntry(
        event_type="appointment.reminder_24h",
        label="Appointment reminder (24h)",
        description=(
            "Celery beat sweep at every 15min fires 24h before the "
            "scheduled time. ``event_id=appointment_reminder_24h:{id}`` "
            "deduplicates across overlapping sweep ticks."
        ),
        sample_payload={
            "appointment_id": "00000000-0000-0000-0000-000000000000",
            "contact_id": "00000000-0000-0000-0000-000000000000",
            "scheduled_at": "2026-07-01T10:00:00+05:30",
            "location": "Bengaluru Showroom",
            "appointment": {
                "id": "00000000-0000-0000-0000-000000000000",
                "title": "Showroom walk-through",
                "purpose": "showroom_visit",
                "scheduled_at": "2026-07-01T10:00:00+05:30",
                "duration_min": 60,
                "location": "Bengaluru Showroom",
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
    )
)
_register(
    CatalogEntry(
        event_type="appointment.reminder_1h",
        label="Appointment reminder (1h)",
        description=(
            "Celery beat sweep at every 15min fires 1h before the "
            "scheduled time. ``event_id=appointment_reminder_1h:{id}`` "
            "deduplicates across overlapping sweep ticks."
        ),
        sample_payload={
            "appointment_id": "00000000-0000-0000-0000-000000000000",
            "contact_id": "00000000-0000-0000-0000-000000000000",
            "scheduled_at": "2026-07-01T10:00:00+05:30",
            "location": "Bengaluru Showroom",
            "appointment": {
                "id": "00000000-0000-0000-0000-000000000000",
                "title": "Showroom walk-through",
                "purpose": "showroom_visit",
                "scheduled_at": "2026-07-01T10:00:00+05:30",
                "duration_min": 60,
                "location": "Bengaluru Showroom",
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
    )
)


# --- Sales ----------------------------------------------------------


_register(
    CatalogEntry(
        event_type="quote.sent",
        label="Quote sent",
        description=(
            "A quote is sent to a contact. Forward-compatible — the "
            "publisher lands when the quotes module ships; the catalog "
            "entry is here today so seeded triggers + the editor's "
            "event picker include the slot."
        ),
        sample_payload={
            "quote_id": "00000000-0000-0000-0000-000000000000",
            "contact_id": "00000000-0000-0000-0000-000000000000",
            "total_amount": "45000.00",
            "currency": "INR",
            "quote": {
                "id": "00000000-0000-0000-0000-000000000000",
                "total_amount": "45000.00",
                "currency": "INR",
                "pdf_url": "https://example.com/quotes/abc.pdf",
                "expires_at": "2026-07-29T00:00:00+00:00",
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
    )
)
_register(
    CatalogEntry(
        event_type="quote.accepted",
        label="Quote accepted",
        description=(
            "The contact accepts the quote (signature flow / portal "
            "action). Forward-compatible — see ``quote.sent``."
        ),
        sample_payload={
            "quote_id": "00000000-0000-0000-0000-000000000000",
            "contact_id": "00000000-0000-0000-0000-000000000000",
            "total_amount": "45000.00",
            "currency": "INR",
            "accepted_at": "2026-06-30T10:00:00+05:30",
            "quote": {
                "id": "00000000-0000-0000-0000-000000000000",
                "total_amount": "45000.00",
                "currency": "INR",
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
    )
)
_register(
    CatalogEntry(
        event_type="invoice.sent",
        label="Invoice sent",
        description=(
            "An invoice is issued + sent to a contact. Fires from "
            "``core.billing.service.issue`` after commit; "
            "``event_id=invoice_sent:{invoice_id}`` deduplicates "
            "replays."
        ),
        sample_payload={
            "invoice_id": "00000000-0000-0000-0000-000000000000",
            "contact_id": "00000000-0000-0000-0000-000000000000",
            "total_amount": "45000.00",
            "currency": "INR",
            "due_date": "2026-07-29",
            "invoice": {
                "id": "00000000-0000-0000-0000-000000000000",
                "number": 4021,
                "total_amount": "45000.00",
                "currency": "INR",
                "issued_at": "2026-06-29T12:00:00+00:00",
                "due_date": "2026-07-29",
                "pdf_url": None,
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
    )
)
_register(
    CatalogEntry(
        event_type="invoice.paid",
        label="Invoice paid",
        description=(
            "An invoice's outstanding balance reaches zero. Fires from "
            "``core.billing.service.record_payment`` once the cumulative "
            "payment sum meets the invoice total; "
            "``event_id=invoice_paid:{invoice_id}`` ensures only one "
            "publish per invoice even on payment-recording replays."
        ),
        sample_payload={
            "invoice_id": "00000000-0000-0000-0000-000000000000",
            "contact_id": "00000000-0000-0000-0000-000000000000",
            "total_amount": "45000.00",
            "currency": "INR",
            "paid_at": "2026-06-30T14:00:00+00:00",
            "payment_method": "upi",
            "invoice": {
                "id": "00000000-0000-0000-0000-000000000000",
                "number": 4021,
                "total_amount": "45000.00",
                "currency": "INR",
                "paid_at": "2026-06-30T14:00:00+00:00",
                "payment_method": "upi",
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
    )
)
_register(
    CatalogEntry(
        event_type="invoice.overdue_7d",
        label="Invoice overdue (7d)",
        description=(
            "Daily Celery beat sweep finds ``issued`` invoices whose "
            "``issued_at`` is more than 7 days ago. "
            "``event_id=invoice_overdue_7d:{invoice_id}`` deduplicates "
            "across daily ticks so each invoice gets at most one "
            "overdue-reminder fire."
        ),
        sample_payload={
            "invoice_id": "00000000-0000-0000-0000-000000000000",
            "contact_id": "00000000-0000-0000-0000-000000000000",
            "total_amount": "45000.00",
            "currency": "INR",
            "issued_at": "2026-06-19T12:00:00+00:00",
            "days_overdue": 7,
            "invoice": {
                "id": "00000000-0000-0000-0000-000000000000",
                "number": 4021,
                "total_amount": "45000.00",
                "currency": "INR",
                "issued_at": "2026-06-19T12:00:00+00:00",
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
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
