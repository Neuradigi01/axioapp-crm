"""Service layer for the contacts module.

Two responsibilities sit here that the router does not duplicate:

1. **`custom_data` validation**. Every write loads the active org's
   `custom_field_definitions` for `entity_type='contact'` and rejects:
   - keys that are not defined,
   - values whose Python type does not match the declared `field_type`,
   - missing required keys on create (update is partial by design).

2. **Filtered list construction**. The `q`, `source`, `tag`, and dynamic
   `custom.<key>=<value>` filters are translated into SQLAlchemy where
   clauses here so the router stays a thin HTTP shim.

Audit events (`contacts.created`, `.updated`, `.deleted`) fire from
inside each write path.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.activities import service as activities_service
from src.app.core.activities.models import ActivityType
from src.app.core.contacts import consent_service, data_access
from src.app.core.contacts.models import Contact
from src.app.core.contacts.schemas import ContactCreate, ContactUpdate
from src.app.shared.audit import log_entity_change, snapshot
from src.app.shared.custom_fields import validate_custom_data
from src.app.shared.db.pagination import paginate
from src.app.shared.db.queries import ensure_found

_CONTACT_ENTITY = "contact"

# Maps the referring table in a FK-RESTRICT violation on tbl_contacts
# to a user-facing dependency label. Only the three RESTRICT tables
# below can trigger this — every other FK to tbl_contacts is
# CASCADE or SET NULL and never blocks a delete.
_CONTACT_FK_BLOCKERS = {
    "tbl_leads": "lead",
    "tbl_appointments": "appointment",
    "tbl_walk_ins": "walk-in",
}
# Match the referring (child) table name, not tbl_contacts itself.
# Postgres formats the error as:
#     update or delete on table "tbl_contacts" violates foreign key
#     constraint "tbl_leads_contact_id_fkey" on table "tbl_leads"
#     DETAIL:  Key (id)=(...) is still referenced from table "tbl_leads".
# The DETAIL line unambiguously names the blocking table; the earlier
# regex just did `re.search(r'on table "(tbl_\w+)"')` and picked up
# "tbl_contacts" (the first hit), which was never in the blocker map,
# so every conflict fell through to the generic fallback message.
_FK_REFERENCING_RE = re.compile(r'is still referenced from table "(tbl_\w+)"')


def _fallback_conflict_message(exc: IntegrityError, *, plural: bool) -> str:
    """Best-effort message from the driver text when the enumeration
    query failed. Extracts the referring table from the DETAIL line —
    covers the case where the enumeration itself blew up (session in
    a bad state, DB gone, etc.)."""
    match = _FK_REFERENCING_RE.search(str(exc.orig) if exc.orig else str(exc))
    label = _CONTACT_FK_BLOCKERS.get(match.group(1)) if match else None
    subject = "one or more contacts have" if plural else "this contact has"
    if label:
        return (
            f"Cannot delete — {subject} at least one linked {label}. "
            f"Delete the {label}{'s' if plural else ''} first, "
            f"or use Anonymise to wipe PII while keeping history."
        )
    return (
        f"Cannot delete — {subject} linked leads, appointments, or walk-ins. "
        "Delete those first, or use Anonymise to wipe PII while keeping history."
    )


def _join_and(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


async def _contact_delete_conflict_detail(
    session: AsyncSession,
    exc: IntegrityError,
    *,
    contact_ids: list[uuid.UUID],
    org_id: uuid.UUID | None,
    plural: bool,
) -> str:
    """Build a specific 'cannot delete' message by counting the actual
    RESTRICT-FK dependencies (leads / appointments / walk-ins) for the
    affected contacts. Falls back to a regex-parsed message from the
    driver error if the count query itself fails."""
    try:
        if plural:
            assert org_id is not None
            counts = await data_access.count_delete_blockers_for_contacts(
                session, ids=contact_ids, org_id=org_id
            )
        else:
            counts = await data_access.count_delete_blockers_for_contact(session, contact_ids[0])
    except SQLAlchemyError:
        return _fallback_conflict_message(exc, plural=plural)

    parts: list[str] = []
    for key, label in (("leads", "lead"), ("appointments", "appointment"), ("walk_ins", "walk-in")):
        n = counts.get(key, 0)
        if n:
            parts.append(f"{n} linked {label}{'s' if n != 1 else ''}")
    if not parts:
        return _fallback_conflict_message(exc, plural=plural)
    subject = "the selected contacts have" if plural else "this contact has"
    return (
        f"Cannot delete — {subject} {_join_and(parts)}. "
        "Delete them first, or use Anonymise to wipe PII while keeping history."
    )


# Server-side whitelist for `?sort=`. Anything outside this set is
# rejected at the router via FastAPI's Literal Query validation, but
# we keep the dict here so the service can resolve the key → column
# without exposing arbitrary attribute access.
_SORT_COLUMNS = {
    "full_name": Contact.full_name,
    "created_at": Contact.created_at,
    "last_activity_at": Contact.last_activity_at,
}


_SNAPSHOT_FIELDS = (
    "id",
    "full_name",
    "phone",
    "email",
    "source",
    "tags",
    "custom_data",
    "assigned_to_id",
)


def _snapshot(contact: Contact) -> dict[str, Any]:
    """JSONB-friendly snapshot for audit `before`/`after`."""
    return snapshot(contact, fields=_SNAPSHOT_FIELDS)


async def get_contact(session: AsyncSession, contact_id: uuid.UUID) -> Contact | None:
    """Public lookup-by-id wrapper. Thin pass-through to the DAL so
    other modules' routers (e.g. notes / activities / files endpoints
    that hang off a contact) don't reach into `contacts.data_access`
    directly."""
    return await data_access.get_contact(session, contact_id)


def _to_e164(phone: str) -> str:
    """Prefix `+` to a phone that lacks it.

    WhatsApp Cloud API sends inbound `from` as `919876543210` (no `+`),
    while contacts persist the full E.164 (`+919876543210`) since the
    validator switched to storing the country code. Callers looking
    up contacts from external channel payloads route through this so
    the exact-match on `Contact.phone` still hits.
    """
    trimmed = (phone or "").strip()
    if not trimmed:
        return trimmed
    return trimmed if trimmed.startswith("+") else "+" + trimmed


async def get_contact_by_phone(session: AsyncSession, phone: str) -> Contact | None:
    """Public lookup-by-phone wrapper. Used by inbound
    conversation routing and walk-in reception to resolve an
    incoming number to a contact. The lookup normalises to E.164
    (`+<country><digits>`) so a bare `919876543210` from a Meta
    webhook still matches a stored `+919876543210`."""
    return await data_access.get_contact_by_phone(session, _to_e164(phone))


async def get_or_create_placeholder_contact(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    external_id: str,
    channel: str,
) -> Contact:
    """Idempotent placeholder-contact resolver
    (``tasks/chatbot-builder`` Case #7 + #23).

    Chatbots need a Contact to persist Ask-* answers against, but an
    inbound from an unknown phone / email doesn't yet have one. This
    helper looks up (phone or email) → Contact; if none exists,
    creates a minimal row flagged ``is_placeholder=true`` for the
    nightly TTL sweeper to reclaim if no meaningful interaction
    follows within 30 days.

    Repeat calls with the same ``(org_id, external_id, channel)``
    return the same row — safe for the matcher to invoke on every
    inbound.
    """
    normalised = (external_id or "").strip()
    if not normalised:
        raise ValueError("external_id is required")

    if channel == "whatsapp":
        # WhatsApp `from` arrives without the leading `+`; contacts
        # persist E.164 (`+919876543210`), so normalise before both
        # the lookup and the new-row insert.
        normalised = _to_e164(normalised)
        existing = await data_access.get_contact_by_phone(session, normalised)
        if existing is not None and existing.org_id == org_id:
            return existing
        contact = Contact(
            org_id=org_id,
            phone=normalised,
            # Was `f"Contact {normalised[-4:]}"`, which surfaced in the
            # inbox as "Contact 3042" — unhelpful. New rows land as
            # `"Unknown WhatsApp contact"` and the frontend list
            # renders the phone number as a secondary line.
            full_name="Unknown WhatsApp contact",
            source="chatbot_placeholder",
            is_placeholder=True,
        )
    elif channel == "email":
        # Contact lookup by email — no data_access helper today so
        # we do a scoped query here. Service layer is allowed to
        # compose reads (not execute them) — this stays on the
        # ``get_contact_by_email`` DAL helper if it exists.
        from sqlalchemy import select

        existing = (
            await session.execute(
                select(Contact).where(
                    Contact.org_id == org_id,
                    Contact.email == normalised,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        contact = Contact(
            org_id=org_id,
            email=normalised,
            full_name=normalised.split("@", 1)[0] if "@" in normalised else normalised,
            source="chatbot_placeholder",
            is_placeholder=True,
        )
    else:
        raise ValueError(f"unsupported channel for placeholder contact: {channel!r}")

    session.add(contact)
    await session.flush()
    await session.commit()
    await session.refresh(contact)
    return contact


async def hydrate_contacts_by_ids(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> list[Contact]:
    """Batched hydrate for the `POST /contacts/hydrate` endpoint.

    Wraps `data_access.list_contacts_by_ids_in_org` so the router
    stays a thin HTTP shim per the Router → Service → DAL rule. The
    DAL query filters by `org_id` in the WHERE clause; ids from
    another tenant simply don't come back.
    """
    return await data_access.list_contacts_by_ids_in_org(session, ids=ids, org_id=org_id)


async def list_contact_custom_field_defs(session: AsyncSession):
    """Ordered list of `custom_field_definitions` for the CSV export
    header. Router doesn't reach into `custom_fields.data_access`
    directly — this shim keeps the layering clean."""
    from src.app.core.custom_fields import data_access as custom_fields_da

    return await custom_fields_da.list_fields_query(session, entity_type="contact")


def insert_contact(session: AsyncSession, contact: Contact) -> None:
    """Public contact-stage wrapper for webhook intake paths that
    need to materialise a placeholder contact (conversations,
    walk-ins) without going through the full create_contact validation
    pipeline."""
    data_access.insert_contact(session, contact)


class InvalidFromHeader(Exception):
    """The RFC 5322 ``From:`` header didn't parse into an email
    address the CRM can attach to a Contact. Raised by
    :func:`auto_create_from_email` when the sender's mail client
    ships a malformed / null / non-email ``From:`` value.

    Caller (the mailgun ingest path) surfaces this by dropping the
    auto-attribution and persisting the message with
    ``contact_id=None``. Never bubbled up to a router / HTTP client
    directly — this is an ingest-side signal, not a user-facing 4xx.
    """


# Constrained loosely — an ``@`` and a non-empty local + domain part.
# The full RFC-5321 regex is 6.4 KB and produces the same signal in
# practice; the strictness we lose here is the strictness we don't
# need for auto-create (a mail that Mailgun accepted has already
# passed a real MTA's validity check).
_MIN_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


async def auto_create_from_email(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    from_header: str,
    source: str = "email_forwarded_address",
) -> Contact:
    """Mint a minimal-shape :class:`Contact` from an RFC ``From:`` header.

    Called by the forwarded-address ingest path
    (:mod:`email.mailgun.ingest_forwarded`) when a message lands from
    an unknown sender AND the endpoint has ``auto_create_contact=True``
    (industry-baseline "auto-create" — HubSpot / Front match this).

    Idempotent w.r.t. the sender's email: a re-fire from the same
    ``From:`` returns the EXISTING contact instead of creating a
    duplicate. Two mechanisms:

      1. Pre-check via :func:`data_access.find_contact_by_email` —
         handles the steady-state "customer sent us another message"
         path in a single SELECT before we ever stage an INSERT.
      2. Post-INSERT :class:`IntegrityError` catch — belt-and-braces
         for the concurrent-worker race (two ``f-<token>`` deliveries
         for the same sender arriving in the same second). Contacts
         doesn't carry a DB-level ``UNIQUE(org_id, email)`` yet, so
         this branch is defensive rather than load-bearing — but
         wiring it now means adding the constraint later is a one-
         line migration, not a behaviour rewrite.

    Raises :class:`InvalidFromHeader` on a header that doesn't parse
    into a syntactically-plausible email address. The caller drops
    the auto-attribution and persists the message with ``contact_id=
    None`` in that branch.
    """
    from email.utils import parseaddr

    display_name, email_addr = parseaddr((from_header or "").strip())
    normalised_email = (email_addr or "").strip().lower()
    if not normalised_email or not _MIN_EMAIL_RE.match(normalised_email):
        raise InvalidFromHeader(
            f"could not parse a mail address out of From: header={from_header!r}"
        )

    # Idempotency pre-check.
    existing = await data_access.find_contact_by_email(
        session, org_id=org_id, email=normalised_email
    )
    if existing is not None:
        return existing

    # Split display name into first/last, preserving unicode.
    first_name, last_name = _split_display_name(display_name)

    try:
        contact = data_access.insert_minimal_contact(
            session,
            org_id=org_id,
            email=normalised_email,
            first_name=first_name,
            last_name=last_name,
            source=source,
        )
        await session.commit()
        await session.refresh(contact)
    except IntegrityError:
        # Concurrent race — some other worker created a contact with
        # the same email between our SELECT and our INSERT. Roll back
        # + re-SELECT so the caller gets a valid Contact back.
        await session.rollback()
        existing = await data_access.find_contact_by_email(
            session, org_id=org_id, email=normalised_email
        )
        if existing is None:
            # Impossible in practice (the INSERT that beat us hasn't
            # been committed yet on the OTHER worker) — surface as a
            # generic 500 rather than silently pretending we handled
            # it. Caller wraps + drops the auto-attribution.
            raise
        return existing

    await audit.log(
        "contact.auto_created_from_inbound_email",
        entity_type="contact",
        entity_id=contact.id,
        org_id=org_id,
        after={
            "email": normalised_email,
            "full_name": contact.full_name,
            "source": source,
        },
    )
    return contact


def _split_display_name(display: str | None) -> tuple[str | None, str | None]:
    """``"Asha Rao" → ("Asha", "Rao")``.

    Single-word names go entirely into ``first_name`` — losing them
    to ``last_name`` would confuse the ``full_name`` composition
    downstream. Preserves unicode (Devanagari, CJK, Cyrillic) since
    we never lower/normalize.
    """
    if not display:
        return None, None
    cleaned = display.strip().strip('"').strip("'")
    if not cleaned:
        return None, None
    parts = cleaned.split(None, 1)
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1].strip() or None


async def create_contact(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: ContactCreate,
    require_all_required: bool = True,
    default_owner_id: uuid.UUID | None = None,
) -> Contact:
    """Create a contact.

    `require_all_required=True` (default) enforces every required
    custom-field definition — the right behaviour for staff-driven
    forms where the operator knows the org's schema.

    Public ingestion paths (embed widget, ad-form webhooks, bulk
    imports of unknown shape) pass `False` because the submitter
    can't possibly know the org's custom-field requirements;
    staff fill in the blanks afterwards via the edit form.

    ``default_owner_id`` is the fallback ``assigned_to_id`` applied when
    the payload doesn't specify one — used by indirect create paths
    (lead-modal stub creates) to attribute a fresh contact to the
    caller so it shows up under their Owner filter. Explicit
    ``payload.assigned_to_id`` still wins when provided.
    """
    cleaned_custom = await validate_custom_data(
        session,
        entity_type=_CONTACT_ENTITY,
        payload=payload.custom_data,
        require_all_required=require_all_required,
    )

    contact = Contact(
        org_id=org_id,
        full_name=payload.full_name,
        phone=payload.phone,
        email=payload.email,
        source=payload.source,
        tags=payload.cleaned_tags(),
        custom_data=cleaned_custom,
        assigned_to_id=payload.assigned_to_id or default_owner_id,
    )
    data_access.insert_contact(session, contact)
    await session.commit()
    await session.refresh(contact)

    await log_entity_change(
        action="contacts.created",
        entity_type="contact",
        entity_id=contact.id,
        after=_snapshot(contact),
    )
    await _publish_contact_created(session=session, org_id=org_id, contact=contact)
    return contact


async def _publish_contact_created(
    *,
    session: AsyncSession,
    org_id: uuid.UUID,
    contact: Contact,
) -> None:
    """Publish ``contact.created`` (``tasks/automation-conditions/``
    follow-up — unlocks the welcome-message flow every CRM operator
    wants).

    Same fire-and-forget try/except pattern as the other publishers
    (``leads._publish_lead_created`` / ``appointments._publish_appointment_booked``)
    — a bus / subscriber failure cannot roll back the freshly-committed
    contact. Event-id ``contact_created:{contact.id}`` deduplicates
    on retry.
    """
    try:
        from sqlalchemy import select as _select

        from src.app.core.events.bus import publish as events_publish
        from src.app.core.tenants.models import Organization

        org = (
            await session.execute(_select(Organization).where(Organization.id == org_id))
        ).scalar_one_or_none()

        payload: dict[str, Any] = {
            "contact_id": str(contact.id),
            "source": contact.source.value if contact.source else None,
            "contact": {
                "id": str(contact.id),
                "full_name": contact.full_name,
                "email": contact.email,
                "phone": contact.phone,
                "source": contact.source.value if contact.source else None,
                "custom_data": contact.custom_data or {},
            },
        }
        if org is not None:
            payload["org"] = {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
            }

        await events_publish(
            "contact.created",
            payload,
            org_id=org_id,
            event_id=f"contact_created:{contact.id}",
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "contacts.create publish_contact_created_failed org=%s contact=%s",
            org_id,
            contact.id,
        )


async def update_contact(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID,
    payload: ContactUpdate,
    org_id: uuid.UUID | None = None,
) -> Contact:
    """Partial update.

    ``org_id`` is optional for back-compat with callers that already
    filter by tenant at the DAL layer, but when supplied the service
    enforces cross-tenant safety on ``assigned_to_id``: a caller with
    ``contacts.write`` cannot reassign a contact to a user that isn't
    an active member of their own org (would otherwise leak referential
    integrity across tenants because ``tbl_users`` is org-agnostic).
    """
    contact = ensure_found(await data_access.get_contact(session, contact_id), entity="contact")

    before = _snapshot(contact)
    changes = payload.model_dump(exclude_unset=True)

    if "custom_data" in changes:
        changes["custom_data"] = await validate_custom_data(
            session,
            entity_type=_CONTACT_ENTITY,
            payload=changes["custom_data"] or {},
            require_all_required=False,
        )

    if "tags" in changes and changes["tags"] is not None:
        seen: dict[str, None] = {}
        for tag in changes["tags"]:
            value = str(tag).strip()
            if value and value not in seen:
                seen[value] = None
        changes["tags"] = list(seen)

    if "assigned_to_id" in changes and changes["assigned_to_id"] is not None and org_id is not None:
        await _assert_user_in_org(
            session,
            org_id=org_id,
            user_uuid=changes["assigned_to_id"],
        )

    # Snapshot tags BEFORE mutation so we can compute the added/removed
    # sets after the commit. Contact.tags is a list column — we treat
    # membership changes as set semantics (order changes don't count).
    tags_before: set[str] = {str(t) for t in (contact.tags or [])}
    # Snapshot phone BEFORE mutation so the WhatsApp/SMS conversation
    # cascade below can detect a real change. The conversation row
    # snapshots ``external_id`` at inbound time; without a cascade the
    # inbox header + next-inbound match go stale the moment an operator
    # adds a country code here.
    phone_before: str | None = contact.phone
    changed_fields = list(changes.keys())

    for key, value in changes.items():
        setattr(contact, key, value)

    if "phone" in changes and contact.phone and contact.phone != phone_before:
        from src.app.core.conversations import service as conversations_service

        await conversations_service.resync_external_id_for_contact_phone(
            session,
            contact_id=contact.id,
            new_phone=contact.phone,
        )

    await session.commit()
    await session.refresh(contact)

    await log_entity_change(
        action="contacts.updated",
        entity_type="contact",
        entity_id=contact.id,
        before=before,
        after=_snapshot(contact),
    )
    if changed_fields:
        await _publish_contact_updated(
            session=session,
            org_id=contact.org_id,
            contact=contact,
            changed_fields=sorted(changed_fields),
        )
        if "tags" in changes:
            tags_after: set[str] = {str(t) for t in (contact.tags or [])}
            added = sorted(tags_after - tags_before)
            removed = sorted(tags_before - tags_after)
            for tag in added:
                await _publish_contact_tag_event(
                    session=session,
                    org_id=contact.org_id,
                    contact=contact,
                    event_type="contact.tag_added",
                    tag=tag,
                )
            for tag in removed:
                await _publish_contact_tag_event(
                    session=session,
                    org_id=contact.org_id,
                    contact=contact,
                    event_type="contact.tag_removed",
                    tag=tag,
                )
    return contact


async def _publish_contact_updated(
    *,
    session: AsyncSession,
    org_id: uuid.UUID,
    contact: Contact,
    changed_fields: list[str],
) -> None:
    """Fire-and-forget ``contact.updated`` publisher. Same shape as
    ``_publish_contact_created`` — subscribers get the current snapshot
    plus a ``changed_fields`` list so a workflow condition can gate on
    "only fire when phone changed" without pulling the before/after
    itself."""
    try:
        from sqlalchemy import select as _select

        from src.app.core.events.bus import publish as events_publish
        from src.app.core.tenants.models import Organization

        org = (
            await session.execute(_select(Organization).where(Organization.id == org_id))
        ).scalar_one_or_none()

        payload: dict[str, Any] = {
            "contact_id": str(contact.id),
            "changed_fields": changed_fields,
            "contact": {
                "id": str(contact.id),
                "full_name": contact.full_name,
                "email": contact.email,
                "phone": contact.phone,
                "source": contact.source.value if contact.source else None,
                "tags": list(contact.tags or []),
                "custom_data": contact.custom_data or {},
            },
        }
        if org is not None:
            payload["org"] = {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
            }

        updated_iso = contact.updated_at.isoformat() if contact.updated_at else ""
        await events_publish(
            "contact.updated",
            payload,
            org_id=org_id,
            event_id=f"contact_updated:{contact.id}:{updated_iso}",
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "contacts.update publish_contact_updated_failed org=%s contact=%s",
            org_id,
            contact.id,
        )


async def _publish_contact_tag_event(
    *,
    session: AsyncSession,
    org_id: uuid.UUID,
    contact: Contact,
    event_type: str,
    tag: str,
) -> None:
    """Fire-and-forget publisher for ``contact.tag_added`` /
    ``contact.tag_removed``. One event per tag mutation so workflow
    conditions can compare on ``tag`` directly (``{{event.tag}}``)
    rather than diffing arrays."""
    try:
        from sqlalchemy import select as _select

        from src.app.core.events.bus import publish as events_publish
        from src.app.core.tenants.models import Organization

        org = (
            await session.execute(_select(Organization).where(Organization.id == org_id))
        ).scalar_one_or_none()

        payload: dict[str, Any] = {
            "contact_id": str(contact.id),
            "tag": tag,
            "tags": list(contact.tags or []),
            "contact": {
                "id": str(contact.id),
                "full_name": contact.full_name,
                "email": contact.email,
                "phone": contact.phone,
            },
        }
        if org is not None:
            payload["org"] = {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
            }

        # event_id keys on the mutation direction + tag so consecutive
        # add/remove/add flips on the same tag don't collapse via dedup.
        updated_iso = contact.updated_at.isoformat() if contact.updated_at else ""
        direction = "added" if event_type.endswith("added") else "removed"
        await events_publish(
            event_type,
            payload,
            org_id=org_id,
            event_id=f"contact_tag_{direction}:{contact.id}:{tag}:{updated_iso}",
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "contacts.update publish_contact_tag_event_failed org=%s contact=%s tag=%s event=%s",
            org_id,
            contact.id,
            tag,
            event_type,
        )


async def delete_contact(session: AsyncSession, *, contact_id: uuid.UUID) -> None:
    """Hard-delete one contact.

    Wraps the FK RESTRICT `IntegrityError` (leads / walk-ins /
    appointments / invoices point at ``tbl_contacts.id`` with
    ``ON DELETE RESTRICT``) into a clean 409 with a hint to use
    Anonymise or delete the dependent rows first. Previous behaviour
    let the raw ``IntegrityError`` bubble up as a 500.

    tasks/workflow-scheduling Step 6 — before the contact row drops,
    every ``tbl_workflow_schedules`` row pointing at this contact is
    deactivated with ``deactivation_reason='contact_deleted'`` +
    audit + owner-notification. The schedule's FK is ``SET NULL``,
    so without this pre-cascade the FK would silently orphan the
    schedule (contact_id → NULL) and it would keep firing against
    ``recipient_not_found``, wasting the fire budget until
    consecutive-empty deactivation catches it 20 fires later.
    """
    contact = ensure_found(await data_access.get_contact(session, contact_id), entity="contact")
    before = _snapshot(contact)
    contact_uuid = contact.id
    contact_org_id = contact.org_id

    # Pre-cascade: deactivate schedules pointing at this contact BEFORE
    # the row drops so the FK SET NULL doesn't leave firing orphans.
    # ``cascade_schedules_on_contact_delete`` commits its own txn —
    # scheduling as the source of truth persists even if the contact
    # delete later fails (better failure mode than the reverse).
    try:
        from src.app.core.workflows import service as workflows_service

        await workflows_service.cascade_schedules_on_contact_delete(
            session, org_id=contact_org_id, contact_id=contact_uuid
        )
    except Exception:
        # Never block the contact delete on a schedule cascade
        # failure — the FK SET NULL still cleans up the FK; the
        # audit + email are best-effort.
        import logging

        logging.getLogger(__name__).exception(
            "contacts.delete_contact schedule_cascade_failed contact=%s",
            contact_uuid,
        )

    await data_access.delete_contact_row(session, contact)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=await _contact_delete_conflict_detail(
                session,
                exc,
                contact_ids=[contact_uuid],
                org_id=contact_org_id,
                plural=False,
            ),
        ) from exc

    await log_entity_change(
        action="contacts.deleted",
        entity_type="contact",
        entity_id=contact_uuid,
        before=before,
    )


async def merge_contacts(
    session: AsyncSession,
    *,
    primary_id: uuid.UUID,
    secondary_id: uuid.UUID,
    org_id: uuid.UUID,
) -> tuple[Contact, dict[str, int]]:
    """Fold ``secondary_id`` into ``primary_id``, delete the secondary.

    Standard fields (name, phone, email, source, assigned_to_id) on
    the primary are preserved as-is — merge is a hygiene action, not
    a field-picker. Tags are union-merged (order preserved, duplicates
    dropped). ``custom_data`` from the secondary fills any key the
    primary doesn't already have; primary values always win on
    conflict.

    Every cross-module row that points at the secondary — activities,
    tasks, leads, walk-ins, appointments, calls, conversations,
    campaign messages, consent events, workflow runs, group members,
    email-sequence enrollments — is re-pointed at the primary by
    ``data_access.reassign_contact_references``. The secondary row is
    then deleted.

    Returns ``(primary_contact_refreshed, rows_reassigned)``. Raises
    404 if either contact is missing; 400 if both ids are equal; 409
    if either belongs to a different org (guards against a URL-hack
    cross-tenant merge).
    """
    if primary_id == secondary_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot merge a contact into itself",
        )

    primary = ensure_found(await data_access.get_contact(session, primary_id), entity="contact")
    secondary = ensure_found(await data_access.get_contact(session, secondary_id), entity="contact")
    if primary.org_id != org_id or secondary.org_id != org_id:
        # Belt-and-suspenders — the ORM tenant filter should have
        # already returned 404 for a cross-tenant id, but check
        # explicitly so a leaked auth session can't ever merge across
        # orgs.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="both contacts must belong to the caller's org",
        )
    if primary.anonymised_at is not None or secondary.anonymised_at is not None:
        # DPDP guard: neither side of a merge may be anonymised.
        # Folding an anonymised row's placeholder name / empty tags
        # into an active contact silently corrupts real PII; folding
        # an active contact into a wiped primary re-populates the
        # placeholder with the secondary's data (un-anonymises via
        # merge). Both must be blocked.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "cannot merge — one of the contacts is anonymised "
                "(DPDP right-to-be-forgotten). Anonymised rows are "
                "immutable to merge to preserve the wipe."
            ),
        )

    before_primary = _snapshot(primary)
    before_secondary = _snapshot(secondary)

    # Union tags — primary order first, then any secondary tags not
    # already present. Preserves the primary's intended tag ordering
    # while picking up anything unique from the secondary.
    merged_tags: dict[str, None] = {t: None for t in (primary.tags or [])}
    for t in secondary.tags or []:
        merged_tags.setdefault(t, None)
    primary.tags = list(merged_tags)

    # Custom data: primary wins on conflict; secondary fills gaps.
    merged_custom: dict[str, Any] = dict(secondary.custom_data or {})
    merged_custom.update(primary.custom_data or {})
    primary.custom_data = merged_custom

    # Repoint every FK / polymorphic ref before deleting the secondary.
    # RESTRICT-FK tables (appointments, leads, walk-ins) would otherwise
    # block the DELETE — the DAL handles them first.
    #
    # ``moved_lead_ids`` — captured now so we can write a per-lead
    # attribution note ("This lead was originally on <secondary
    # name>…") after commit. Every mature CRM (HubSpot, Zoho,
    # Pipedrive) does this so a rep opening a lead can tell which
    # merged-from contact it belonged to originally, without needing
    # a special filter on the list. The IDs come back inside the
    # merge transaction, but we defer the annotation writes until
    # after the commit lands so a failure writing a note doesn't
    # roll back a successful merge.
    try:
        rows_reassigned, moved_lead_ids = await data_access.reassign_contact_references(
            session,
            org_id=org_id,
            primary_id=primary.id,
            secondary_id=secondary.id,
        )
        await data_access.delete_contact_row(session, secondary)
        await session.commit()
    except IntegrityError as exc:
        # Some table still references the secondary despite the DAL
        # sweep — surface a 409 with the underlying constraint so the
        # operator (and support) know which table needs a follow-up
        # repoint rather than seeing the generic "unknown error".
        await session.rollback()
        constraint = getattr(getattr(exc, "orig", None), "diag", None)
        constraint_name = getattr(constraint, "constraint_name", None) if constraint else None
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "cannot merge — a related row still references the "
                "secondary contact"
                + (f" (constraint: {constraint_name})" if constraint_name else "")
                + ". Report this to support so we can add the missing repoint."
            ),
        ) from exc
    except SQLAlchemyError as exc:
        # Any other DB-layer failure: expose the driver-level message
        # (missing table / column / bad syntax) so the operator can
        # diagnose instead of getting the opaque middleware fallback
        # ("An unknown error occurred!"). ``exc.orig`` carries the
        # psycopg error text with the actual relation/column name.
        await session.rollback()
        orig = getattr(exc, "orig", None)
        driver_msg = str(orig) if orig is not None else str(exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"merge failed at commit: {type(exc).__name__}: {driver_msg[:400]}",
        ) from exc
    await session.refresh(primary)

    # Audit rows: one on each side so both timelines carry the merge.
    # `contacts.merged` on the primary; `contacts.merged_into` on the
    # secondary (though the row is gone, the audit log survives).
    await log_entity_change(
        action="contacts.merged",
        entity_type="contact",
        entity_id=primary.id,
        before=before_primary,
        after=_snapshot(primary),
    )
    await log_entity_change(
        action="contacts.merged_into",
        entity_type="contact",
        entity_id=secondary.id,
        before=before_secondary,
        after={"merged_into_contact_id": str(primary.id)},
    )

    # Timeline breadcrumb on the primary so a rep browsing the
    # activities tab sees "merged from <name>" alongside other events.
    # Fire-and-forget: the merge/commit is already durable at this
    # point, so a failing timeline write must NOT surface as a 500 —
    # operator would rage-retry a merge that already ran and hit "both
    # contacts must belong to the caller's org" (secondary is gone).
    try:
        await activities_service.log(
            entity_type="contact",
            entity_id=primary.id,
            type=ActivityType.note,
            payload={
                "text": (
                    f"Merged from {before_secondary.get('full_name') or 'contact'}. "
                    f"Repointed rows: "
                    + ", ".join(f"{k}={v}" for k, v in rows_reassigned.items() if v)
                ),
                "merged_from_contact_id": str(secondary.id),
            },
            org_id=org_id,
        )
    except Exception:  # noqa: BLE001 — best-effort audit breadcrumb.
        pass

    # Per-lead attribution: one note per moved lead so its Activities
    # tab shows "This lead was originally on <secondary name>, merged
    # into <primary name>." Same best-effort semantics as the summary
    # note above — a note-write failure never rolls back the merge.
    # Loop bounded by the number of leads the secondary owned (never
    # more than the org's total leads), so worst-case is a per-lead
    # timeline insert.
    secondary_name = before_secondary.get("full_name") or "another contact"
    primary_name = _snapshot(primary).get("full_name") or "this contact"
    for lead_id in moved_lead_ids:
        try:
            await activities_service.log(
                entity_type="lead",
                entity_id=lead_id,
                type=ActivityType.note,
                payload={
                    "text": (
                        f"This lead was originally on contact "
                        f"'{secondary_name}' and was moved to "
                        f"'{primary_name}' during a contact merge."
                    ),
                    "merged_from_contact_id": str(secondary.id),
                    "merged_from_contact_name": secondary_name,
                    "system": True,
                },
                org_id=org_id,
            )
        except Exception:  # noqa: BLE001 — best-effort per-lead note.
            # One lead's note failure must not stop the others.
            continue

    return primary, rows_reassigned


async def anonymise_contact(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID,
    org_id: uuid.UUID,
    reason: str | None,
    actor_user_id: uuid.UUID | None,
) -> Contact:
    """DPDP right-to-be-forgotten. Wipe PII on the contact row without
    breaking cross-module FKs.

    Hard-delete isn't an option — appointments, leads, invoices,
    workflow runs all point at ``tbl_contacts.id`` and either
    (a) block the DELETE (RESTRICT FKs) or (b) drop the historical
    linkage (SET NULL / CASCADE) — both undesirable when the
    obligation is to remove the *personal data*, not the *audit trail*.
    So instead we:

    1. Reject the call if the contact is already anonymised (409).
    2. Overwrite ``full_name`` with a stable placeholder (so timeline
       renders on other entities still show *something*),
       ``phone`` / ``email`` → NULL, ``tags`` → [], ``custom_data`` →
       {}.
    3. Force-flip both consent channels (WhatsApp via
       ``consent_service.record_transition`` so the immutable log
       captures the ``manual_override`` source; email opt-in via
       direct row assignment because email has no equivalent service).
    4. Stamp ``anonymised_at = now`` — the ``anonymised_at IS NOT
       NULL`` predicate becomes the site-wide guard for excluding the
       row from campaigns, automations, list defaults, etc.
    5. Emit an audit row carrying the operator's ``reason`` so a
       future auditor can trace *why* the wipe happened. Reason itself
       is NOT stored on the row (it's operator-supplied text — could
       contain a ticket reference or "as requested" — that goes in
       the audit log, not on the anonymised contact).
    """
    contact = ensure_found(await data_access.get_contact(session, contact_id), entity="contact")
    if contact.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="contact does not belong to the caller's org",
        )
    if contact.anonymised_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="contact is already anonymised",
        )

    before = _snapshot(contact)
    now = datetime.now(UTC)

    # 1. Wipe PII columns. `full_name` gets a stable placeholder so
    # timelines on other entities (leads, appointments, invoices...)
    # still render *something* rather than blowing up on empty
    # strings.
    placeholder = f"Anonymised contact {str(contact.id)[:8]}"
    contact.full_name = placeholder
    contact.phone = None
    contact.email = None
    contact.tags = []
    contact.custom_data = {}
    contact.anonymised_at = now

    # 2. Force WhatsApp opt-out with a proper consent event so the
    # immutable log carries the manual-override transition. Skips
    # cleanly if already opted_out (idempotent).
    if contact.whatsapp_opt_in_status != "opted_out":
        await consent_service.record_transition(
            session,
            contact=contact,
            new_status="opted_out",
            source="manual_entry",
            actor_user_id=actor_user_id,
            reason=(reason or "dpdp right-to-be-forgotten"),
            commit=False,
        )

    # 3. Force email opt-out (no service abstraction — direct assign).
    contact.email_opt_in_status = "opted_out"
    contact.email_opt_out = True
    if contact.email_opt_out_at is None:
        contact.email_opt_out_at = now

    await session.commit()
    await session.refresh(contact)

    await log_entity_change(
        action="contacts.anonymised",
        entity_type="contact",
        entity_id=contact.id,
        before=before,
        after={
            "full_name": contact.full_name,
            "phone": None,
            "email": None,
            "tags": [],
            "custom_data": {},
            "anonymised_at": now.isoformat(),
            "reason": reason,
        },
    )
    return contact


async def list_contacts(
    session: AsyncSession,
    *,
    q: str | None = None,
    sources: list[str] | None = None,
    tags: list[str] | None = None,
    assigned_to_ids: list[uuid.UUID] | None = None,
    custom_filters: Iterable[tuple[str, str]] = (),
    sort: Literal["full_name", "created_at", "last_activity_at"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    page: int = 1,
    size: int = 50,
    exclude_anonymised: bool = False,
    lead_statuses: list[str] | None = None,
    lead_stages: list[str] | None = None,
    lead_sources: list[str] | None = None,
    lead_form_ids: list[uuid.UUID] | None = None,
) -> tuple[list[Contact], int]:
    """Paginated list with optional filters. Returns (rows, total).

    - `q` matches full_name / phone / email via ILIKE; trigram GIN index
      accelerates the full_name leg.
    - `sources`, `tags`, `assigned_to_ids` are multi-value OR-sets — a
      row matches when its value belongs to the given list. Backs the
      column-header filter popovers on the list page (an operator can
      tick e.g. Source ∈ {Walk-in, Website}). `None` / empty means no
      filter on that column.
    - `custom_filters` is an iterable of `(key, expected_string_value)`
      pairs that translate to `custom_data ->> key = :value`. String
      compare is intentional: it's what the master prompt example uses
      and avoids server-side type guessing.
    - `sort` + `order` are server-whitelisted via `_SORT_COLUMNS`.
      `last_activity_at desc` appends `NULLS LAST` so never-touched
      contacts sink to the bottom.
    """
    base = data_access.build_contact_list_query(
        q=q,
        sources=sources,
        tags=tags,
        assigned_to_ids=assigned_to_ids,
        custom_filters=custom_filters,
        sort_column=_SORT_COLUMNS[sort],
        sort=sort,
        order=order,
        exclude_anonymised=exclude_anonymised,
        lead_statuses=lead_statuses,
        lead_stages=lead_stages,
        lead_sources=lead_sources,
        lead_form_ids=lead_form_ids,
    )
    return await paginate(session, base, page=page, size=size)


# --- Reassign / bulk actions -------------------------------------------------


async def _assert_user_in_org(
    session: AsyncSession, *, org_id: uuid.UUID, user_uuid: uuid.UUID
) -> None:
    """422 if the target user has no active membership in this org.

    Prevents a malicious / mistaken cross-tenant reassign — an attacker
    on Org A submitting a user UUID belonging only to Org B should be
    rejected before we mutate the row.
    """
    is_member = await data_access.is_user_active_member_of_org(
        session, user_uuid=user_uuid, org_id=org_id
    )
    if not is_member:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="target user is not a member of this organisation",
        )


def _reassign_payload(
    *, from_id: uuid.UUID | None, to_id: uuid.UUID | None, note: str | None
) -> dict[str, Any]:
    """JSONB body for the `reassign` activity row."""
    return {
        "from": str(from_id) if from_id is not None else None,
        "to": str(to_id) if to_id is not None else None,
        "note": note,
    }


async def reassign_contact(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID,
    org_id: uuid.UUID,
    assigned_to_id: uuid.UUID | None,
    note: str | None,
    actor_user_id: uuid.UUID | None,
    commit: bool = True,
) -> Contact:
    """Single-row reassign. Writes an audit `Activity(type=reassign)` on the
    same session so the contact update + the timeline row commit atomically.

    `commit=False` lets `bulk_reassign_contacts` batch many reassigns into
    one transaction without N intermediate commits.
    """
    contact = ensure_found(await data_access.get_contact(session, contact_id), entity="contact")

    if assigned_to_id is not None:
        await _assert_user_in_org(session, org_id=org_id, user_uuid=assigned_to_id)

    before_id = contact.assigned_to_id
    if before_id == assigned_to_id:
        # No-op — don't write an audit row for an identity reassign.
        return contact

    before = _snapshot(contact)
    contact.assigned_to_id = assigned_to_id

    # Follow-the-pack cascade — reassign related walk-ins, leads,
    # appointments, and tasks whose current owner matches the
    # contact's previous owner. Skipped when the contact had no
    # owner (nothing was "following" it) or when nothing to update.
    if before_id is not None:
        await data_access.cascade_owner_to_related(
            session,
            contact_id=contact.id,
            from_owner_id=before_id,
            to_owner_id=assigned_to_id,
        )

    await activities_service.record_in_session(
        session,
        org_id=org_id,
        entity_type="contact",
        entity_id=contact.id,
        type=ActivityType.reassign,
        payload=_reassign_payload(from_id=before_id, to_id=assigned_to_id, note=note),
        user_id=actor_user_id,
    )

    if commit:
        await session.commit()
        await session.refresh(contact)

    await audit.log(
        "contacts.reassigned",
        entity_type="contact",
        entity_id=contact.id,
        before=before,
        after=_snapshot(contact),
    )
    return contact


async def bulk_reassign_contacts(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
    assigned_to_id: uuid.UUID | None,
    note: str | None,
    actor_user_id: uuid.UUID | None,
) -> int:
    """Reassign N contacts in a single transaction. Returns rows touched.

    Each row gets its own audit `Activity(type=reassign)` so the timeline
    on every contact shows the transfer. Rows whose owner doesn't change
    are silently skipped (no-op activity).
    """
    if assigned_to_id is not None:
        await _assert_user_in_org(session, org_id=org_id, user_uuid=assigned_to_id)

    # Batched hydrate — collapses the old per-id round-trips into a
    # single `WHERE id IN (:ids)` read. Activity inserts stay per-row
    # (each contact needs its own timeline entry) but there's no reason
    # the SELECTs should be N.
    contacts = await data_access.list_contacts_by_ids_in_org(session, ids=ids, org_id=org_id)

    reassigned = 0
    for contact in contacts:
        if contact.assigned_to_id == assigned_to_id:
            continue
        before_id = contact.assigned_to_id
        contact.assigned_to_id = assigned_to_id
        # Follow-the-pack cascade for every contact whose owner changed
        # (same rule as single reassign — see `reassign_contact`).
        if before_id is not None:
            await data_access.cascade_owner_to_related(
                session,
                contact_id=contact.id,
                from_owner_id=before_id,
                to_owner_id=assigned_to_id,
            )
        await activities_service.record_in_session(
            session,
            org_id=org_id,
            entity_type="contact",
            entity_id=contact.id,
            type=ActivityType.reassign,
            payload=_reassign_payload(from_id=before_id, to_id=assigned_to_id, note=note),
            user_id=actor_user_id,
        )
        reassigned += 1

    await session.commit()
    return reassigned


async def bulk_delete_contacts(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> int:
    """Hard-delete N contacts. Matches single `DELETE /contacts/{id}` semantics.

    `org_id` is enforced in the WHERE clause as a belt to the tenant RLS
    policy — the auto ORM tenant filter only injects on SELECTs.

    Wraps FK RESTRICT `IntegrityError` (see `delete_contact` for the
    list of dependent tables) into a clean 409 — otherwise a
    single-row conflict would raw-500 the whole batch. The FK check
    fires at statement execution (not deferred), so the try/except
    must wrap the DAL call, not `commit()`.
    """
    try:
        deleted = await data_access.delete_contacts_in_org(session, ids=ids, org_id=org_id)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=await _contact_delete_conflict_detail(
                session,
                exc,
                contact_ids=ids,
                org_id=org_id,
                plural=True,
            ),
        ) from exc
    return deleted


async def bulk_add_tag_contacts(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    tag: str,
    org_id: uuid.UUID,
) -> int:
    """Append `tag` to the `tags` array on every selected contact.

    Uses Postgres `array_append` so the same tag isn't duplicated.
    Trims whitespace; rejects empty after trim (the request schema
    already enforces non-empty + length cap).
    """
    clean = tag.strip()
    if not clean:
        # Schema already enforces min_length=1; raise here so a direct
        # caller sees a clean 422 instead of silent "updated 0 rows".
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="tag must not be blank",
        )
    # `tags = CASE WHEN clean = ANY(tags) THEN tags ELSE array_append(tags, clean) END`
    # via SQLAlchemy text expression — keeps the per-row decision in PG.
    rowcount = await data_access.bulk_append_tag(session, ids=ids, tag=clean, org_id=org_id)
    await session.commit()
    return rowcount


# --- Duplicate check + CSV export -------------------------------------------


# Hard cap on CSV export rows. Past this the caller has to narrow their
# filter — protects the streamed response from blowing memory and
# protects the user from a giant download they didn't intend.
EXPORT_CSV_MAX_ROWS = 50_000


def _normalise_phone_suffix(raw: str) -> str | None:
    """Strip non-digit and return the last 10 digits.

    Matches "9000000001", "+91 9000000001", "+91-9000000001", and
    "919000000001" against the same key. None when input is too
    short to be meaningful (< 6 digits — guards against `q=1` style
    accidental queries from blanking the dedup screen).
    """
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) < 6:
        return None
    return digits[-10:] if len(digits) >= 10 else digits


CONTACT_TAG_OPTIONS_LIMIT = 500


async def list_contact_tags(session: AsyncSession, *, org_id: uuid.UUID) -> list[str]:
    """Tag vocabulary for the list page's Tags column filter. Org-wide,
    so the options don't depend on which page of contacts is showing."""
    return await data_access.list_distinct_contact_tags(
        session, org_id=org_id, limit=CONTACT_TAG_OPTIONS_LIMIT
    )


async def check_duplicate(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    phone: str | None = None,
    email: str | None = None,
    exclude_id: uuid.UUID | None = None,
) -> list[Contact]:
    """Return contacts that match the given phone (last-10-digit suffix)
    or email (case-insensitive exact) within the caller's tenant.

    Both parameters are optional. With neither, returns an empty list
    (no point hitting the DB). `exclude_id` lets the edit modal skip
    matching against the row being edited.
    """
    has_phone = bool(phone and phone.strip())
    has_email = bool(email and email.strip())
    if not has_phone and not has_email:
        return []

    phone_suffix = _normalise_phone_suffix(phone or "") if has_phone else None
    email_lower = (email or "").strip().lower() if has_email else None
    return await data_access.find_duplicate_candidates(
        session,
        org_id=org_id,
        phone_suffix=phone_suffix,
        email_lower=email_lower,
        exclude_id=exclude_id,
    )


async def export_contacts_csv_rows(
    session: AsyncSession,
    *,
    q: str | None = None,
    sources: list[str] | None = None,
    tags: list[str] | None = None,
    assigned_to_ids: list[uuid.UUID] | None = None,
    custom_filters: Iterable[tuple[str, str]] = (),
) -> list[Contact]:
    """Resolve the export filter to a list of contacts (≤ EXPORT_CSV_MAX_ROWS).

    Mirrors `list_contacts`'s filter logic — keeps the export and the
    list view in sync without re-implementing the WHERE clauses. Raises
    422 when the result set exceeds the cap so the caller can prompt
    the user to narrow.
    """
    total = await data_access.count_contacts_filtered(
        session,
        q=q,
        sources=sources,
        tags=tags,
        assigned_to_ids=assigned_to_ids,
        custom_filters=custom_filters,
    )
    if total > EXPORT_CSV_MAX_ROWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"export would return {total} rows (cap {EXPORT_CSV_MAX_ROWS}); "
                "narrow the filter and try again"
            ),
        )

    return await data_access.list_contacts_for_export(
        session,
        q=q,
        sources=sources,
        tags=tags,
        assigned_to_ids=assigned_to_ids,
        custom_filters=custom_filters,
    )
