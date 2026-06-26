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

import uuid
from typing import Any, Iterable, Literal

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.activities import service as activities_service
from src.app.core.activities.models import ActivityType
from src.app.core.contacts import data_access
from src.app.core.contacts.models import Contact
from src.app.core.contacts.schemas import ContactCreate, ContactUpdate
from src.app.shared.audit import log_entity_change, snapshot
from src.app.shared.custom_fields import validate_custom_data
from src.app.shared.db.pagination import paginate
from src.app.shared.db.queries import ensure_found


_CONTACT_ENTITY = "contact"

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
    "notes",
    "custom_data",
    "assigned_to_id",
)


def _snapshot(contact: Contact) -> dict[str, Any]:
    """JSONB-friendly snapshot for audit `before`/`after`."""
    return snapshot(contact, fields=_SNAPSHOT_FIELDS)


async def get_contact(
    session: AsyncSession, contact_id: uuid.UUID
) -> Contact | None:
    """Public lookup-by-id wrapper. Thin pass-through to the DAL so
    other modules' routers (e.g. notes / activities / files endpoints
    that hang off a contact) don't reach into `contacts.data_access`
    directly."""
    return await data_access.get_contact(session, contact_id)


async def get_contact_by_phone(
    session: AsyncSession, phone: str
) -> Contact | None:
    """Public lookup-by-phone wrapper. Used by inbound
    conversation routing and walk-in reception to resolve an
    incoming number to a contact."""
    return await data_access.get_contact_by_phone(session, phone)


def insert_contact(session: AsyncSession, contact: Contact) -> None:
    """Public contact-stage wrapper for webhook intake paths that
    need to materialise a placeholder contact (conversations,
    walk-ins) without going through the full create_contact validation
    pipeline."""
    data_access.insert_contact(session, contact)


async def create_contact(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: ContactCreate,
    require_all_required: bool = True,
) -> Contact:
    """Create a contact.

    `require_all_required=True` (default) enforces every required
    custom-field definition — the right behaviour for staff-driven
    forms where the operator knows the org's schema.

    Public ingestion paths (embed widget, ad-form webhooks, bulk
    imports of unknown shape) pass `False` because the submitter
    can't possibly know the org's custom-field requirements;
    staff fill in the blanks afterwards via the edit form.
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
        notes=payload.notes,
        custom_data=cleaned_custom,
        assigned_to_id=payload.assigned_to_id,
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
    return contact


async def update_contact(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID,
    payload: ContactUpdate,
) -> Contact:
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

    for key, value in changes.items():
        setattr(contact, key, value)
    await session.commit()
    await session.refresh(contact)

    await log_entity_change(
        action="contacts.updated",
        entity_type="contact",
        entity_id=contact.id,
        before=before,
        after=_snapshot(contact),
    )
    return contact


async def delete_contact(
    session: AsyncSession, *, contact_id: uuid.UUID
) -> None:
    contact = ensure_found(await data_access.get_contact(session, contact_id), entity="contact")
    before = _snapshot(contact)
    contact_uuid = contact.id
    await data_access.delete_contact_row(session, contact)
    await session.commit()

    await log_entity_change(
        action="contacts.deleted",
        entity_type="contact",
        entity_id=contact_uuid,
        before=before,
    )


async def list_contacts(
    session: AsyncSession,
    *,
    q: str | None = None,
    source: str | None = None,
    tag: str | None = None,
    assigned_to_id: uuid.UUID | None = None,
    custom_filters: Iterable[tuple[str, str]] = (),
    sort: Literal["full_name", "created_at", "last_activity_at"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    page: int = 1,
    size: int = 50,
) -> tuple[list[Contact], int]:
    """Paginated list with optional filters. Returns (rows, total).

    - `q` matches full_name / phone / email via ILIKE; trigram GIN index
      accelerates the full_name leg.
    - `source` is exact match.
    - `tag` checks the value is contained in the `tags` array.
    - `assigned_to_id` filters by owner. None means no filter (show all);
      the "show only unassigned" UI predicate is wired in Step 2 via a
      separate query param so we don't overload the UUID semantic here.
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
        source=source,
        tag=tag,
        assigned_to_id=assigned_to_id,
        custom_filters=custom_filters,
        sort_column=_SORT_COLUMNS[sort],
        sort=sort,
        order=order,
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
        await _assert_user_in_org(
            session, org_id=org_id, user_uuid=assigned_to_id
        )

    before_id = contact.assigned_to_id
    if before_id == assigned_to_id:
        # No-op — don't write an audit row for an identity reassign.
        return contact

    before = _snapshot(contact)
    contact.assigned_to_id = assigned_to_id

    await activities_service.record_in_session(
        session,
        org_id=org_id,
        entity_type="contact",
        entity_id=contact.id,
        type=ActivityType.reassign,
        payload=_reassign_payload(
            from_id=before_id, to_id=assigned_to_id, note=note
        ),
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
        await _assert_user_in_org(
            session, org_id=org_id, user_uuid=assigned_to_id
        )

    reassigned = 0
    for cid in ids:
        contact = await data_access.get_contact(session, cid)
        if contact is None:
            continue
        if contact.assigned_to_id == assigned_to_id:
            continue
        before_id = contact.assigned_to_id
        contact.assigned_to_id = assigned_to_id
        await activities_service.record_in_session(
            session,
            org_id=org_id,
            entity_type="contact",
            entity_id=contact.id,
            type=ActivityType.reassign,
            payload=_reassign_payload(
                from_id=before_id, to_id=assigned_to_id, note=note
            ),
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
    """
    deleted = await data_access.delete_contacts_in_org(
        session, ids=ids, org_id=org_id
    )
    await session.commit()
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
        return 0
    # `tags = CASE WHEN clean = ANY(tags) THEN tags ELSE array_append(tags, clean) END`
    # via SQLAlchemy text expression — keeps the per-row decision in PG.
    rowcount = await data_access.bulk_append_tag(
        session, ids=ids, tag=clean, org_id=org_id
    )
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

    phone_suffix = (
        _normalise_phone_suffix(phone or "") if has_phone else None
    )
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
    source: str | None = None,
    tag: str | None = None,
    assigned_to_id: uuid.UUID | None = None,
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
        source=source,
        tag=tag,
        assigned_to_id=assigned_to_id,
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
        source=source,
        tag=tag,
        assigned_to_id=assigned_to_id,
        custom_filters=custom_filters,
    )
