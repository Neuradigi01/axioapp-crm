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
2. Add a ``CatalogEntry`` here — include ``condition_fields`` so the
   customer-friendly builder can render its dropdown (see below).
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

Condition fields (``tasks/automation-conditions/`` Step 1):
    Each entry ships a ``condition_fields`` tuple of
    :class:`~core.automation.field_specs.FieldSpec` — the fields the
    "Only if" builder's dropdown surfaces for that event. Every
    field's ``path`` MUST resolve into the entry's ``sample_payload``
    (drift guard raises at import time otherwise). Enum fields
    declare an ``enum_resolver`` key that step-2's live registry
    dispatches to at request time.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from src.app.core.automation._pack_context import get_current_pack
from src.app.core.automation.field_specs import (
    GROUP_APPOINTMENT,
    GROUP_CONTACT,
    GROUP_INVOICE,
    GROUP_LEAD,
    GROUP_ORG,
    GROUP_QUOTE,
    GROUP_TRANSITION,
    GROUP_USER,
    FieldSpec,
    FieldType,
    path_resolves,
)


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One row in the discovery catalog.

    ``pack_id`` (tasks/automation-conditions/ Step 7) is ``None`` for
    core events (visible to every org) and set to the pack slug for
    events registered by a pack's ``event_catalog.py``. The service
    layer filters the ``/event-types`` response by the caller org's
    ``template_id`` so a pack's events only surface for orgs that
    installed the pack. Auto-populated by :func:`_register` from the
    pack-import context — pack files don't need to hardcode their
    own slug on every registration.
    """

    event_type: str
    label: str
    description: str
    sample_payload: dict[str, Any]
    condition_fields: tuple[FieldSpec, ...] = field(default_factory=tuple)
    pack_id: str | None = None


_CATALOG: dict[str, CatalogEntry] = {}


def _register(entry: CatalogEntry) -> None:
    # Auto-tag pack registrations with the pack slug from the
    # import-context ContextVar. The module-registry walker
    # (`core/module_registry.py:_discover_pack_event_catalogs`) sets
    # the context before importing each pack's `event_catalog.py`.
    # Core registrations run outside any pack import, so the context
    # is None and the entry stays untouched.
    current_pack = get_current_pack()
    if current_pack is not None and entry.pack_id is None:
        entry = replace(entry, pack_id=current_pack)

    # Drift guard — every declared FieldSpec path must resolve into
    # the entry's sample_payload. Catches ``lead.stage`` vs
    # ``lead.pipeline_stage`` typos the moment code lands, before a
    # customer picks the wrong field and the runtime evaluator
    # silently no-matches every event.
    for spec in entry.condition_fields:
        if not path_resolves(entry.sample_payload, spec.path):
            raise ValueError(
                f"FieldSpec drift: event {entry.event_type!r} declares "
                f"path {spec.path!r} but that path does not resolve into "
                f"sample_payload. Update the spec or the payload so they "
                f"match — the customer-friendly condition builder relies "
                f"on this invariant."
            )
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
        condition_fields=(
            FieldSpec(path="user.email", label="Email", type=FieldType.text, group=GROUP_USER),
            FieldSpec(
                path="user.full_name", label="Full name", type=FieldType.text, group=GROUP_USER
            ),
            FieldSpec(path="org.slug", label="Org slug", type=FieldType.text, group=GROUP_ORG),
        ),
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
        condition_fields=(
            FieldSpec(
                path="user.email",
                label="Invitee email",
                type=FieldType.text,
                group=GROUP_USER,
            ),
            FieldSpec(
                path="invited_by_user_id",
                label="Invited by",
                type=FieldType.enum,
                group=GROUP_USER,
                enum_resolver="users",
            ),
        ),
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
        condition_fields=(
            FieldSpec(path="user.email", label="Email", type=FieldType.text, group=GROUP_USER),
            FieldSpec(
                path="user.full_name", label="Full name", type=FieldType.text, group=GROUP_USER
            ),
        ),
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
                "custom_data": {},
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
                "custom_data": {},
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
        condition_fields=(
            FieldSpec(
                path="source",
                label="Source",
                type=FieldType.enum,
                group=GROUP_LEAD,
                enum_resolver="lead_sources",
            ),
            FieldSpec(
                path="lead.pipeline_stage",
                label="Stage",
                type=FieldType.enum,
                group=GROUP_LEAD,
                enum_resolver="pipeline_stages",
            ),
            FieldSpec(
                path="lead.status",
                label="Status",
                type=FieldType.enum,
                group=GROUP_LEAD,
                enum_resolver="lead_statuses",
            ),
            FieldSpec(
                path="lead.assigned_to_id",
                label="Assigned to",
                type=FieldType.enum,
                group=GROUP_LEAD,
                enum_resolver="users",
                help_text="Empty when the lead is unassigned — use 'is empty' to filter.",
            ),
            FieldSpec(
                path="lead.budget",
                label="Budget",
                type=FieldType.currency,
                group=GROUP_LEAD,
            ),
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
            FieldSpec(
                path="contact.phone",
                label="Phone",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
    )
)
_register(
    CatalogEntry(
        event_type="lead.assigned",
        label="Lead assigned",
        description=(
            "A lead's owner is set or changed — fires when a lead is "
            "created with an assignee, single-row reassigned, or "
            "bulk-reassigned. ``from_user_id`` is null on the "
            "first-time assignment (fresh lead) and non-null when a "
            "reassignment moves ownership between reps, so operators "
            "can add ``from_user_id IS NULL`` conditions to target only "
            "one branch. Round-robin auto-assign inside a workflow is "
            "**not** covered here — the seeded auto-triage workflow "
            "already notifies the assignee inline. "
            "``event_id=lead_assigned:{lead_id}:{to_user_id}`` "
            "deduplicates identity-reassign replays."
        ),
        sample_payload={
            # Flat top-level keys so condition AST paths like
            # `field='to_user_id'` work without nesting; nested
            # `user` / `lead` / `contact` / `org` dicts carry the
            # variable renderer's lookups. `from_user_id` is null
            # when the row previously had no assignee.
            "lead_id": "00000000-0000-0000-0000-000000000000",
            "contact_id": "00000000-0000-0000-0000-000000000000",
            "from_user_id": None,
            "to_user_id": "00000000-0000-0000-0000-000000000000",
            "assigned_at": "2026-07-21T13:00:00+00:00",
            "user": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Priya Kapoor",
                "email": "priya@example.com",
                "role": "Sales",
            },
            "lead": {
                "id": "00000000-0000-0000-0000-000000000000",
                "source": "widget",
                "status": "active",
                "pipeline_stage": "new",
                "assigned_to_id": "00000000-0000-0000-0000-000000000000",
                "budget": None,
                "custom_data": {},
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
                "custom_data": {},
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
        condition_fields=(
            FieldSpec(
                path="to_user_id",
                label="Assigned to (new)",
                type=FieldType.enum,
                group=GROUP_TRANSITION,
                enum_resolver="users",
            ),
            FieldSpec(
                path="from_user_id",
                label="Assigned to (previous)",
                type=FieldType.enum,
                group=GROUP_TRANSITION,
                enum_resolver="users",
                help_text=(
                    "Empty on a first-time assignment — use 'is empty' to "
                    "target only fresh assignments."
                ),
            ),
            FieldSpec(
                path="lead.pipeline_stage",
                label="Stage",
                type=FieldType.enum,
                group=GROUP_LEAD,
                enum_resolver="pipeline_stages",
            ),
            FieldSpec(
                path="lead.source",
                label="Source",
                type=FieldType.enum,
                group=GROUP_LEAD,
                enum_resolver="lead_sources",
            ),
            FieldSpec(
                path="lead.status",
                label="Status",
                type=FieldType.enum,
                group=GROUP_LEAD,
                enum_resolver="lead_statuses",
            ),
        ),
    )
)
_register(
    CatalogEntry(
        event_type="lead.status_changed",
        label="Lead status changed",
        description="The lead transitions between pipeline stages.",
        sample_payload={
            "lead": {"id": "00000000-0000-0000-0000-000000000000", "custom_data": {}},
            "from_status": "new",
            "to_status": "qualified",
            "contact": {"first_name": "Asha"},
        },
        condition_fields=(
            FieldSpec(
                path="to_status",
                label="New stage",
                type=FieldType.enum,
                group=GROUP_TRANSITION,
                enum_resolver="pipeline_stages",
            ),
            FieldSpec(
                path="from_status",
                label="Previous stage",
                type=FieldType.enum,
                group=GROUP_TRANSITION,
                enum_resolver="pipeline_stages",
            ),
        ),
    )
)
_register(
    CatalogEntry(
        event_type="lead.score_threshold",
        label="Lead score crossed threshold",
        description="Lead score crosses a configured threshold (e.g. ≥75).",
        sample_payload={
            "lead": {"id": "00000000-0000-0000-0000-000000000000", "score": 75, "custom_data": {}},
            "threshold": 75,
            "direction": "up",
            "contact": {"first_name": "Asha"},
        },
        condition_fields=(
            FieldSpec(
                path="lead.score",
                label="Score",
                type=FieldType.number,
                group=GROUP_LEAD,
            ),
            FieldSpec(
                path="threshold",
                label="Threshold crossed",
                type=FieldType.number,
                group=GROUP_LEAD,
            ),
            FieldSpec(
                path="direction",
                label="Direction",
                type=FieldType.enum,
                group=GROUP_LEAD,
                enum_resolver="direction_updown",
                help_text="'up' when the score just crossed above the threshold, 'down' when below.",
            ),
        ),
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
                "custom_data": {},
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
        condition_fields=(
            FieldSpec(
                path="age_turning",
                label="Age turning",
                type=FieldType.number,
                group=GROUP_CONTACT,
            ),
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
            FieldSpec(
                path="contact.phone",
                label="Phone",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
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
                "custom_data": {},
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
                "custom_data": {},
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
        condition_fields=(
            FieldSpec(
                path="days_since_last_activity",
                label="Days since last activity",
                type=FieldType.number,
                group=GROUP_LEAD,
            ),
            FieldSpec(
                path="lead.pipeline_stage",
                label="Stage",
                type=FieldType.enum,
                group=GROUP_LEAD,
                enum_resolver="pipeline_stages",
            ),
            FieldSpec(
                path="lead.status",
                label="Status",
                type=FieldType.enum,
                group=GROUP_LEAD,
                enum_resolver="lead_statuses",
            ),
            FieldSpec(
                path="lead.assigned_to_id",
                label="Assigned to",
                type=FieldType.enum,
                group=GROUP_LEAD,
                enum_resolver="users",
            ),
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
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
                "custom_data": {},
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
                "custom_data": {},
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
        condition_fields=(
            FieldSpec(
                path="appointment.purpose",
                label="Purpose",
                type=FieldType.enum,
                group=GROUP_APPOINTMENT,
                enum_resolver="appointment_purposes",
            ),
            FieldSpec(
                path="location",
                label="Location",
                type=FieldType.text,
                group=GROUP_APPOINTMENT,
            ),
            FieldSpec(
                path="appointment.duration_min",
                label="Duration (minutes)",
                type=FieldType.number,
                group=GROUP_APPOINTMENT,
            ),
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
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
                "custom_data": {},
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
                "custom_data": {},
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
        condition_fields=(
            FieldSpec(
                path="appointment.purpose",
                label="Purpose",
                type=FieldType.enum,
                group=GROUP_APPOINTMENT,
                enum_resolver="appointment_purposes",
            ),
            FieldSpec(
                path="location",
                label="Location",
                type=FieldType.text,
                group=GROUP_APPOINTMENT,
            ),
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
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
                "custom_data": {},
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
                "custom_data": {},
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
        condition_fields=(
            FieldSpec(
                path="appointment.purpose",
                label="Purpose",
                type=FieldType.enum,
                group=GROUP_APPOINTMENT,
                enum_resolver="appointment_purposes",
            ),
            FieldSpec(
                path="location",
                label="Location",
                type=FieldType.text,
                group=GROUP_APPOINTMENT,
            ),
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
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
                "custom_data": {},
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
        condition_fields=(
            FieldSpec(
                path="quote.total_amount",
                label="Total amount",
                type=FieldType.currency,
                group=GROUP_QUOTE,
            ),
            FieldSpec(
                path="quote.currency",
                label="Currency",
                type=FieldType.text,
                group=GROUP_QUOTE,
                help_text="ISO 4217 code — e.g. INR, USD.",
            ),
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
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
                "custom_data": {},
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
        condition_fields=(
            FieldSpec(
                path="quote.total_amount",
                label="Total amount",
                type=FieldType.currency,
                group=GROUP_QUOTE,
            ),
            FieldSpec(
                path="quote.currency",
                label="Currency",
                type=FieldType.text,
                group=GROUP_QUOTE,
            ),
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
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
                "custom_data": {},
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
        condition_fields=(
            FieldSpec(
                path="invoice.total_amount",
                label="Total amount",
                type=FieldType.currency,
                group=GROUP_INVOICE,
            ),
            FieldSpec(
                path="invoice.currency",
                label="Currency",
                type=FieldType.text,
                group=GROUP_INVOICE,
            ),
            FieldSpec(
                path="invoice.number",
                label="Invoice number",
                type=FieldType.number,
                group=GROUP_INVOICE,
            ),
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
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
                "custom_data": {},
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
        condition_fields=(
            FieldSpec(
                path="invoice.total_amount",
                label="Total amount",
                type=FieldType.currency,
                group=GROUP_INVOICE,
            ),
            FieldSpec(
                path="invoice.currency",
                label="Currency",
                type=FieldType.text,
                group=GROUP_INVOICE,
            ),
            FieldSpec(
                path="payment_method",
                label="Payment method",
                type=FieldType.enum,
                group=GROUP_INVOICE,
                enum_resolver="payment_methods",
            ),
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
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
                "custom_data": {},
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
        condition_fields=(
            FieldSpec(
                path="days_overdue",
                label="Days overdue",
                type=FieldType.number,
                group=GROUP_INVOICE,
            ),
            FieldSpec(
                path="invoice.total_amount",
                label="Total amount",
                type=FieldType.currency,
                group=GROUP_INVOICE,
            ),
            FieldSpec(
                path="invoice.currency",
                label="Currency",
                type=FieldType.text,
                group=GROUP_INVOICE,
            ),
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
    )
)


# --- Contacts (Step-7 follow-up: new events) --------------------------


_register(
    CatalogEntry(
        event_type="contact.created",
        label="Contact created",
        description=(
            "A new contact is created via any surface — staff form, "
            "walk-in check-in, embed widget, ad-form webhook, bulk "
            "import. Fires once from ``core.contacts.service.create_contact`` "
            "after commit; ``event_id=contact_created:{contact_id}`` "
            "deduplicates retries. Enables the classic welcome-message "
            "flow every CRM operator wants."
        ),
        sample_payload={
            "contact_id": "00000000-0000-0000-0000-000000000000",
            "source": "widget",
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
                "source": "widget",
                "custom_data": {},
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
        condition_fields=(
            FieldSpec(
                path="source",
                label="Source",
                type=FieldType.text,
                group=GROUP_CONTACT,
                help_text="Where the contact came from (e.g. widget, walk_in, bulk_import).",
            ),
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
            FieldSpec(
                path="contact.phone",
                label="Phone",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
    )
)


# --- Appointment lifecycle (Step-7 follow-up) ------------------------

# Shared sample_payload for the 4 lifecycle events — same envelope
# shape as appointment.booked; each event carries the current
# `status` in the nested `appointment` dict + a few extras where
# relevant (reschedule adds from_scheduled_at + to_scheduled_at;
# cancelled + no_show optionally carry a reason).
_APPT_LIFECYCLE_SAMPLE_PAYLOAD: dict[str, Any] = {
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
        "status": "cancelled",
        "custom_data": {},
    },
    "contact": {
        "id": "00000000-0000-0000-0000-000000000000",
        "full_name": "Asha Mehta",
        "email": "asha@example.com",
        "phone": "+919876543210",
        "custom_data": {},
    },
    "org": {
        "id": "00000000-0000-0000-0000-000000000000",
        "name": "Demo Workspace",
        "slug": "demo-workspace",
    },
}

_APPT_LIFECYCLE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        path="appointment.purpose",
        label="Purpose",
        type=FieldType.enum,
        group=GROUP_APPOINTMENT,
        enum_resolver="appointment_purposes",
    ),
    FieldSpec(
        path="location",
        label="Location",
        type=FieldType.text,
        group=GROUP_APPOINTMENT,
    ),
    FieldSpec(
        path="contact.email",
        label="Email",
        type=FieldType.text,
        group=GROUP_CONTACT,
    ),
)


_register(
    CatalogEntry(
        event_type="appointment.cancelled",
        label="Appointment cancelled",
        description=(
            "Customer or staff cancelled a scheduled appointment. Fires "
            "from PATCH /appointments/{id} status transition OR from "
            "the bulk-cancel endpoint. ``event_id=appointment_cancelled:{id}`` "
            "deduplicates replays. Enables the rescue flow — auto "
            "WhatsApp: 'Sorry we missed you, can we reschedule?'"
        ),
        sample_payload=_APPT_LIFECYCLE_SAMPLE_PAYLOAD,
        condition_fields=_APPT_LIFECYCLE_FIELDS,
    )
)
_register(
    CatalogEntry(
        event_type="appointment.no_show",
        label="Appointment no-show",
        description=(
            "Appointment slot passed without the customer showing up. "
            "Fires from PATCH /appointments/{id} when staff mark the "
            "row as ``no_show``. Enables the silent-loss rescue flow — "
            "chase for a rebook before the lead cools."
        ),
        sample_payload={
            **_APPT_LIFECYCLE_SAMPLE_PAYLOAD,
            "appointment": {**_APPT_LIFECYCLE_SAMPLE_PAYLOAD["appointment"], "status": "no_show"},
        },
        condition_fields=_APPT_LIFECYCLE_FIELDS,
    )
)
_register(
    CatalogEntry(
        event_type="appointment.completed",
        label="Appointment completed",
        description=(
            "Staff marks a scheduled appointment as ``completed``. "
            "Enables post-visit flows — review request, next-step nudge, "
            "quote follow-up."
        ),
        sample_payload={
            **_APPT_LIFECYCLE_SAMPLE_PAYLOAD,
            "appointment": {**_APPT_LIFECYCLE_SAMPLE_PAYLOAD["appointment"], "status": "completed"},
        },
        condition_fields=_APPT_LIFECYCLE_FIELDS,
    )
)
_register(
    CatalogEntry(
        event_type="appointment.rescheduled",
        label="Appointment rescheduled",
        description=(
            "Appointment's ``scheduled_at`` shifted to a new slot. Fires "
            "from ``core.appointments.service.reschedule_appointment``. "
            "``event_id`` includes the new slot ISO so multiple "
            "reschedules on the same appointment dedupe per-slot rather "
            "than collapsing into one fire."
        ),
        sample_payload={
            **_APPT_LIFECYCLE_SAMPLE_PAYLOAD,
            "from_scheduled_at": "2026-07-01T10:00:00+05:30",
            "to_scheduled_at": "2026-07-02T14:00:00+05:30",
            "reason": "Customer requested",
            "appointment": {
                **_APPT_LIFECYCLE_SAMPLE_PAYLOAD["appointment"],
                "status": "scheduled",
                "from_scheduled_at": "2026-07-01T10:00:00+05:30",
                "to_scheduled_at": "2026-07-02T14:00:00+05:30",
                "reason": "Customer requested",
            },
        },
        condition_fields=_APPT_LIFECYCLE_FIELDS,
    )
)


# --- Walk-ins (Step-7 follow-up) -------------------------------------


_register(
    CatalogEntry(
        event_type="walk_in.converted",
        label="Walk-in converted to lead",
        description=(
            "A shop-floor walk-in is converted to a lead. Fires from "
            "``core.walk_ins.service.convert_walk_in_to_lead`` after "
            "commit. Enables handoff flows — auto WhatsApp to the "
            "customer once a rep formally captures them as a lead."
        ),
        sample_payload={
            "walk_in_id": "00000000-0000-0000-0000-000000000000",
            "contact_id": "00000000-0000-0000-0000-000000000000",
            "lead_id": "00000000-0000-0000-0000-000000000000",
            "walk_in": {
                "id": "00000000-0000-0000-0000-000000000000",
                "assigned_to_id": "00000000-0000-0000-0000-000000000000",
                "budget": "150000.00",
            },
            "lead": {
                "id": "00000000-0000-0000-0000-000000000000",
                "source": "walk_in",
                "pipeline_stage": "new",
                "custom_data": {},
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
                "custom_data": {},
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
        condition_fields=(
            FieldSpec(
                path="walk_in.assigned_to_id",
                label="Assigned to",
                type=FieldType.enum,
                group=GROUP_LEAD,
                enum_resolver="users",
            ),
            FieldSpec(
                path="lead.pipeline_stage",
                label="Stage",
                type=FieldType.enum,
                group=GROUP_LEAD,
                enum_resolver="pipeline_stages",
            ),
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
    )
)


# --- Billing (Step-7 follow-up: void + overdue escalation) -----------


_register(
    CatalogEntry(
        event_type="invoice.voided",
        label="Invoice voided",
        description=(
            "An invoice is voided (cancelled after issue). Fires from "
            "``core.billing.service.void``. Enables apology emails to "
            "the customer + accounting-team reconciliation alerts."
        ),
        sample_payload={
            "invoice_id": "00000000-0000-0000-0000-000000000000",
            "contact_id": "00000000-0000-0000-0000-000000000000",
            "total_amount": "45000.00",
            "currency": "INR",
            "reason": "Duplicate invoice",
            "invoice": {
                "id": "00000000-0000-0000-0000-000000000000",
                "number": 4021,
                "total_amount": "45000.00",
                "currency": "INR",
                "issued_at": "2026-06-29T12:00:00+00:00",
                "reason": "Duplicate invoice",
            },
            "contact": {
                "id": "00000000-0000-0000-0000-000000000000",
                "full_name": "Asha Mehta",
                "email": "asha@example.com",
                "phone": "+919876543210",
                "custom_data": {},
            },
            "org": {
                "id": "00000000-0000-0000-0000-000000000000",
                "name": "Demo Workspace",
                "slug": "demo-workspace",
            },
        },
        condition_fields=(
            FieldSpec(
                path="invoice.total_amount",
                label="Total amount",
                type=FieldType.currency,
                group=GROUP_INVOICE,
            ),
            FieldSpec(
                path="invoice.currency",
                label="Currency",
                type=FieldType.text,
                group=GROUP_INVOICE,
            ),
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
    )
)

# Shared sample payload + condition fields for the two additional
# overdue tiers — same envelope as invoice.overdue_7d, days_overdue
# distinguishes them.
_OVERDUE_SAMPLE_PAYLOAD: dict[str, Any] = {
    "invoice_id": "00000000-0000-0000-0000-000000000000",
    "contact_id": "00000000-0000-0000-0000-000000000000",
    "total_amount": "45000.00",
    "currency": "INR",
    "issued_at": "2026-06-12T12:00:00+00:00",
    "days_overdue": 14,
    "invoice": {
        "id": "00000000-0000-0000-0000-000000000000",
        "number": 4021,
        "total_amount": "45000.00",
        "currency": "INR",
        "issued_at": "2026-06-12T12:00:00+00:00",
    },
    "contact": {
        "id": "00000000-0000-0000-0000-000000000000",
        "full_name": "Asha Mehta",
        "email": "asha@example.com",
        "phone": "+919876543210",
        "custom_data": {},
    },
    "org": {
        "id": "00000000-0000-0000-0000-000000000000",
        "name": "Demo Workspace",
        "slug": "demo-workspace",
    },
}

_OVERDUE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        path="days_overdue",
        label="Days overdue",
        type=FieldType.number,
        group=GROUP_INVOICE,
    ),
    FieldSpec(
        path="invoice.total_amount",
        label="Total amount",
        type=FieldType.currency,
        group=GROUP_INVOICE,
    ),
    FieldSpec(
        path="invoice.currency",
        label="Currency",
        type=FieldType.text,
        group=GROUP_INVOICE,
    ),
    FieldSpec(
        path="contact.email",
        label="Email",
        type=FieldType.text,
        group=GROUP_CONTACT,
    ),
)

_register(
    CatalogEntry(
        event_type="invoice.overdue_14d",
        label="Invoice overdue (14d)",
        description=(
            "Daily Celery beat sweep finds ``issued`` invoices whose "
            "``issued_at`` is more than 14 days ago. "
            "``event_id=invoice_overdue_14d:{invoice_id}`` deduplicates "
            "across daily ticks so each invoice fires this tier at "
            "most once. Escalation-ladder second rung (7d is polite; "
            "14d is a firmer nudge)."
        ),
        sample_payload={**_OVERDUE_SAMPLE_PAYLOAD, "days_overdue": 14},
        condition_fields=_OVERDUE_FIELDS,
    )
)
_register(
    CatalogEntry(
        event_type="invoice.overdue_30d",
        label="Invoice overdue (30d)",
        description=(
            "Daily Celery beat sweep finds ``issued`` invoices whose "
            "``issued_at`` is more than 30 days ago. Final rung of the "
            "escalation ladder — warning-tone copy, manager CC. "
            "``event_id=invoice_overdue_30d:{invoice_id}`` deduplicates."
        ),
        sample_payload={
            **_OVERDUE_SAMPLE_PAYLOAD,
            "days_overdue": 30,
            "issued_at": "2026-05-29T12:00:00+00:00",
        },
        condition_fields=_OVERDUE_FIELDS,
    )
)


# --- Reviews (Step-7 follow-up) --------------------------------------


_REVIEW_SAMPLE_PAYLOAD: dict[str, Any] = {
    "review_id": "00000000-0000-0000-0000-000000000000",
    "contact_id": "00000000-0000-0000-0000-000000000000",
    "rating": 5,
    "review": {
        "id": "00000000-0000-0000-0000-000000000000",
        "rating": 5,
        "status": "replied",
        "source": "google",
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
}


_register(
    CatalogEntry(
        event_type="review.replied",
        label="Review replied",
        description=(
            "Staff replied to a customer review. Fires from "
            "``core.reviews.service.reply_to_review``. Enables "
            "thank-you-for-the-feedback acknowledgements + reply-visibility "
            "notifications to the reviewing contact."
        ),
        sample_payload={
            **_REVIEW_SAMPLE_PAYLOAD,
            "reply_preview": "Thanks so much for the kind words!",
        },
        condition_fields=(
            FieldSpec(
                path="review.rating",
                label="Rating",
                type=FieldType.number,
                group=GROUP_CONTACT,
            ),
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
    )
)
_register(
    CatalogEntry(
        event_type="review.escalated",
        label="Review escalated",
        description=(
            "A review was escalated to a manager for handling (usually "
            "a negative review needing intervention). Fires from "
            "``core.reviews.service.escalate_review``. Enables internal "
            "manager alerts + SLA-timer flows for high-touch response."
        ),
        sample_payload={
            **_REVIEW_SAMPLE_PAYLOAD,
            "review": {**_REVIEW_SAMPLE_PAYLOAD["review"], "status": "escalated", "rating": 1},
            "rating": 1,
            "reason": "Customer complaint about product quality",
        },
        condition_fields=(
            FieldSpec(
                path="review.rating",
                label="Rating",
                type=FieldType.number,
                group=GROUP_CONTACT,
            ),
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
    )
)


# --- Email tracking (Step-7 follow-up) -------------------------------


_EMAIL_TRACKING_SAMPLE_PAYLOAD: dict[str, Any] = {
    "message_id": "00000000-0000-0000-0000-000000000000",
    "contact_id": "00000000-0000-0000-0000-000000000000",
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
}


_register(
    CatalogEntry(
        event_type="email.opened",
        label="Email opened",
        description=(
            "Customer opened a tracked email — the tracking pixel loaded. "
            "Fires from ``core.email.tracking.router._record_open``. "
            "``event_id=email_opened:{message_id}`` deduplicates the "
            "many re-renders (email client rehydrations, forwarded "
            "threads) into a single automation run per message. "
            "Enables high-intent alerts — 'customer opened your quote'."
        ),
        sample_payload=_EMAIL_TRACKING_SAMPLE_PAYLOAD,
        condition_fields=(
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
    )
)
_register(
    CatalogEntry(
        event_type="email.clicked",
        label="Email link clicked",
        description=(
            "Customer clicked a tracked link in an email. Fires from "
            "``core.email.tracking.router._record_click``. Higher-intent "
            "signal than ``email.opened`` — customer took an action. "
            "``target_url`` carries the URL they clicked. "
            "``event_id=email_clicked:{message_id}`` deduplicates."
        ),
        sample_payload={
            **_EMAIL_TRACKING_SAMPLE_PAYLOAD,
            "target_url": "https://example.com/quote/abc",
        },
        condition_fields=(
            FieldSpec(
                path="target_url",
                label="Target URL",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
            FieldSpec(
                path="contact.email",
                label="Email",
                type=FieldType.text,
                group=GROUP_CONTACT,
            ),
        ),
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


def is_visible_to(entry: CatalogEntry, template_id: str | None) -> bool:
    """True when this entry is visible to an org whose installed
    pack is ``template_id`` (``tasks/automation-conditions/`` Step 7).

    Core entries (``pack_id is None``) are visible to every org.
    Pack entries are visible only to orgs whose ``template_id``
    matches the entry's ``pack_id``. Passing ``template_id=None``
    matches an org with no installed pack — such orgs see only
    core entries.

    Matches the sidebar-registry filter behaviour in
    :meth:`ModuleRegistry.list_for_user` — same predicate, different
    registry — so operators experience consistent "what my org
    has" gating across the sidebar + the automation picker.
    """
    if entry.pack_id is None:
        return True
    return entry.pack_id == template_id


__all__ = [
    "CatalogEntry",
    "get_entry",
    "is_known",
    "is_visible_to",
    "list_catalog",
]
