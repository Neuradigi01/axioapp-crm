"""Data-access layer for the contacts module.

Pure query helpers — no transactions, no audit, no commits. Leaf
module; never imports a `service.py`.

Two duplicate-by-shape patterns in the codebase: by id (the canonical
"hydrate this contact" call) and by phone (walk-in reception's
"do we already know this number?" check + conversation routing's
inbound-message-to-contact resolver).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import (
    and_,
    func,
    or_,
    select,
    text,
)
from sqlalchemy import (
    delete as sa_delete,
)
from sqlalchemy import (
    update as sa_update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, Select

from src.app.core.contacts.models import Contact
from src.app.core.users.models import OrganizationMember, User


async def get_contact(session: AsyncSession, contact_id: uuid.UUID) -> Contact | None:
    """Resolve a contact by its UUID PK.

    Tenant scoping is applied automatically by the `do_orm_execute`
    listener (Contact is `TenantScoped`), so the row is only returned
    when it belongs to the active request's org. Callers that run
    outside a tenant context (Celery, scripts) must set
    `RequestContext.org_id` first.
    """
    result = await session.execute(select(Contact).where(Contact.id == contact_id))
    return result.scalar_one_or_none()


async def get_contact_by_phone(session: AsyncSession, phone: str) -> Contact | None:
    """Resolve a contact by phone number.

    Used by walk-in reception (existing-customer detection) and by
    the conversation router (inbound WhatsApp / SMS → contact mapping).
    The phone column is indexed but not unique — multiple contacts
    can share a number across orgs (different tenants). The tenant
    auto-filter narrows the result to the active org.
    """
    result = await session.execute(select(Contact).where(Contact.phone == phone))
    return result.scalar_one_or_none()


def insert_contact(session: AsyncSession, contact: Contact) -> None:
    """Register an already-constructed Contact for INSERT. Caller
    commits or flushes. Used by webhook intake paths that need to
    materialise a placeholder contact for an unknown phone number
    (conversations, walk-ins)."""
    session.add(contact)


async def delete_contact_row(session: AsyncSession, contact: Contact) -> None:
    """Hard-delete one Contact row."""
    await session.delete(contact)


# --- filter helpers -----------------------------------------------------


def _build_filters(
    *,
    q: str | None,
    source: str | None,
    tag: str | None,
    assigned_to_id: uuid.UUID | None,
    custom_filters: Iterable[tuple[str, str]],
) -> list[ColumnElement[bool]]:
    """Shared filter assembler used by list / export / count helpers."""
    filters: list[ColumnElement[bool]] = []
    if q:
        like = f"%{q}%"
        filters.append(
            or_(
                Contact.full_name.ilike(like),
                Contact.phone.ilike(like),
                Contact.email.ilike(like),
            )
        )
    if source:
        filters.append(Contact.source == source)
    if tag:
        filters.append(Contact.tags.contains([tag]))
    if assigned_to_id is not None:
        filters.append(Contact.assigned_to_id == assigned_to_id)
    for key, value in custom_filters:
        filters.append(Contact.custom_data[key].astext == value)
    return filters


def build_contact_list_query(
    *,
    q: str | None,
    source: str | None,
    tag: str | None,
    assigned_to_id: uuid.UUID | None,
    custom_filters: Iterable[tuple[str, str]],
    sort_column: Any,
    sort: str,
    order: str,
) -> Select[tuple[Contact]]:
    """Assemble the paginated list query with filter + sort applied.

    Returned `Select` is fed to `shared.db.pagination.paginate` by the
    caller. `sort_column` is the whitelisted column object the service
    resolves from `_SORT_COLUMNS` (kept there so the alphabet of valid
    keys lives next to the route schema).
    """
    filters = _build_filters(
        q=q,
        source=source,
        tag=tag,
        assigned_to_id=assigned_to_id,
        custom_filters=custom_filters,
    )
    base = select(Contact)
    if filters:
        base = base.where(and_(*filters))

    if sort == "last_activity_at":
        primary = (
            sort_column.asc().nulls_last() if order == "asc" else sort_column.desc().nulls_last()
        )
        # Rows with no activity yet fall back to newest-created — the
        # standard CRM "recency wins" ordering that the frontend list
        # relies on to surface just-added contacts near the top even
        # before their first touch. ``Contact.id`` stays as a final
        # deterministic tie for absolute stability.
        return base.order_by(primary, Contact.created_at.desc(), Contact.id.desc())
    primary = sort_column.asc() if order == "asc" else sort_column.desc()
    return base.order_by(primary, Contact.id.desc())


async def is_user_active_member_of_org(
    session: AsyncSession, *, user_uuid: uuid.UUID, org_id: uuid.UUID
) -> bool:
    """True iff the user has an active membership row in the given org."""
    result = await session.execute(
        select(OrganizationMember.id)
        .join(User, User.id == OrganizationMember.user_member_id)
        .where(
            User.legacy_uuid == user_uuid,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.is_active.is_(True),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def list_contacts_by_ids_in_org(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> list[Contact]:
    """Batched hydrate for the bulk-reassign path. Empty input → empty
    list without a round-trip. `org_id` is asserted in the WHERE clause
    as a belt to the ORM tenant filter."""
    if not ids:
        return []
    result = await session.execute(
        select(Contact).where(Contact.id.in_(ids), Contact.org_id == org_id)
    )
    return list(result.scalars().all())


async def delete_contacts_in_org(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> int:
    """Hard-delete contacts by id within one org. Returns rowcount."""
    if not ids:
        return 0
    result = await session.execute(
        sa_delete(Contact).where(Contact.id.in_(ids), Contact.org_id == org_id)
    )
    return int(result.rowcount or 0)


async def bulk_append_tag(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    tag: str,
    org_id: uuid.UUID,
) -> int:
    """Append `tag` to each contact's `tags` array (if missing).

    Postgres `array_append` keeps the operation atomic per row.
    Returns rowcount.
    """
    if not ids:
        return 0
    result = await session.execute(
        sa_update(Contact)
        .where(Contact.id.in_(ids), Contact.org_id == org_id)
        .where(~Contact.tags.contains([tag]))
        .values(tags=func.array_append(Contact.tags, tag))
    )
    return int(result.rowcount or 0)


async def find_duplicate_candidates(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    phone_suffix: str | None,
    email_lower: str | None,
    exclude_id: uuid.UUID | None,
    limit: int = 10,
) -> list[Contact]:
    """Return contacts matching either the last-10-digit phone suffix
    or the lower(email) — within one org. Empty input → empty list."""
    or_filters: list[ColumnElement[bool]] = []
    if phone_suffix:
        or_filters.append(
            func.regexp_replace(Contact.phone, r"\D", "", "g").like(f"%{phone_suffix}")
        )
    if email_lower:
        or_filters.append(func.lower(Contact.email) == email_lower)
    if not or_filters:
        return []
    stmt = (
        select(Contact)
        .where(Contact.org_id == org_id)
        # Anonymised rows carry a placeholder full_name and null
        # phone/email — surfacing them as "possible duplicates" in the
        # create/edit modal is misleading (operator could click
        # through to a wiped record).
        .where(Contact.anonymised_at.is_(None))
        .where(or_(*or_filters))
        .order_by(Contact.created_at.desc())
        .limit(limit)
    )
    if exclude_id is not None:
        stmt = stmt.where(Contact.id != exclude_id)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def count_contacts_filtered(
    session: AsyncSession,
    *,
    q: str | None,
    source: str | None,
    tag: str | None,
    assigned_to_id: uuid.UUID | None,
    custom_filters: Iterable[tuple[str, str]],
) -> int:
    """Total contacts matching the filter set — used by CSV-export cap."""
    filters = _build_filters(
        q=q,
        source=source,
        tag=tag,
        assigned_to_id=assigned_to_id,
        custom_filters=custom_filters,
    )
    stmt = select(func.count()).select_from(Contact)
    if filters:
        stmt = stmt.where(and_(*filters))
    return int((await session.execute(stmt)).scalar_one())


async def find_birthdays_on(
    session: AsyncSession,
    *,
    month: int,
    day: int,
) -> list[Contact]:
    """Return every Contact whose ``date_of_birth`` matches the
    ``(month, day)`` pair — used by the Step-12 daily birthday scan
    (``core.automation.scheduler.scan_birthdays``).

    The scanner is cross-tenant — it opens a session WITHOUT setting
    ``RequestContext.org_id`` so the ``do_orm_execute`` tenant filter
    is a no-op + the scan returns every org's birthdays in one pass.
    The caller reads ``contact.org_id`` off each row + supplies it
    when publishing the per-org ``contact.birthday`` event.

    Leap-day birthdays (Feb 29) are handled by matching the literal
    pair — in non-leap years those contacts simply don't surface;
    the operator can choose to add a "rolled to Mar 1" condition in
    the trigger if desired.
    """
    stmt = (
        select(Contact)
        .where(Contact.date_of_birth.is_not(None))
        .where(func.extract("month", Contact.date_of_birth) == month)
        .where(func.extract("day", Contact.date_of_birth) == day)
    )
    return list((await session.execute(stmt)).scalars().all())


async def reassign_contact_references(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    primary_id: uuid.UUID,
    secondary_id: uuid.UUID,
) -> dict[str, int]:
    """Repoint every cross-module row that references ``secondary_id``
    to ``primary_id`` inside the given org.

    Called by ``service.merge_contacts`` right before the secondary row
    is deleted. Every UPDATE is org-scoped even though the FK alone
    would guarantee isolation — belt + suspenders, matches every other
    DAL statement in the codebase.

    Returns a per-table row-count map (``{"activities": 3, "leads": 1,
    ...}``) so the service can render a "merged X activities + Y leads"
    audit line.

    Tables covered (grouped by relationship shape):

    * **Direct FK columns.** appointments · leads · walk-ins · calls ·
      campaign_messages · conversations · reviews · automation_runs ·
      workflow_runs (2 columns) · invoices · consent_events ·
      email_sequence_enrollments · whatsapp_flow_submissions ·
      custom_orders (furniture pack) — a straight UPDATE ... WHERE
      contact_id = :secondary.
    * **Polymorphic entity refs.** activities · tasks — UPDATE where
      entity_type = 'contact' AND entity_id = :secondary.
    * **Join tables with unique (contact_id, X).** contact_group_members
      — DELETE any row where primary is already a member of that group,
      then UPDATE the rest. Otherwise the UPDATE would violate the
      partial unique index.

    Ordering: reassign group memberships (dedupe-first) before the
    generic UPDATEs so a failed UPDATE on the join table doesn't leave
    a half-merged state. Then the RESTRICT-FK targets so the eventual
    secondary DELETE isn't blocked. Then SET NULL / CASCADE targets.
    Order doesn't affect correctness but keeps the failure surface
    small.
    """
    counts: dict[str, int] = {}

    # Group memberships: dedupe (drop secondary rows for groups the
    # primary is already in) then reassign the rest.
    dedupe_group_members = text(
        """
        DELETE FROM tbl_contact_group_members
        WHERE org_id = :org_id
          AND contact_id = :secondary
          AND group_id IN (
            SELECT group_id FROM tbl_contact_group_members
            WHERE org_id = :org_id AND contact_id = :primary
          )
        """
    )
    counts["contact_group_members_deduped"] = (
        await session.execute(
            dedupe_group_members,
            {"org_id": org_id, "primary": primary_id, "secondary": secondary_id},
        )
    ).rowcount or 0

    # Every direct-FK table shares the same UPDATE shape. Iterate a
    # (table, count-key) list so the map is populated per-table with
    # zero repetition.
    _FK_TARGETS: tuple[tuple[str, str], ...] = (
        ("tbl_appointments", "appointments"),
        ("tbl_leads", "leads"),
        ("tbl_walk_ins", "walk_ins"),
        ("tbl_calls", "calls"),
        ("tbl_campaign_messages", "campaign_messages"),
        ("tbl_conversations", "conversations"),
        ("tbl_reviews", "reviews"),
        ("tbl_automation_runs", "automation_runs"),
        ("tbl_invoices", "invoices"),
        ("tbl_consent_events", "consent_events"),
        ("tbl_email_sequence_enrollments", "email_sequence_enrollments"),
        ("tbl_contact_group_members", "contact_group_members"),
    )
    for tbl, key in _FK_TARGETS:
        stmt = text(
            f"UPDATE {tbl} SET contact_id = :primary "
            f"WHERE org_id = :org_id AND contact_id = :secondary"
        )
        counts[key] = (
            await session.execute(
                stmt,
                {"org_id": org_id, "primary": primary_id, "secondary": secondary_id},
            )
        ).rowcount or 0

    # Workflow runs carry two contact refs (subject + latest actor);
    # both need updating.
    for column in ("contact_id", "latest_contact_id"):
        stmt = text(
            f"UPDATE tbl_workflow_runs SET {column} = :primary "
            f"WHERE org_id = :org_id AND {column} = :secondary"
        )
        counts[f"workflow_runs_{column}"] = (
            await session.execute(
                stmt,
                {"org_id": org_id, "primary": primary_id, "secondary": secondary_id},
            )
        ).rowcount or 0

    # Polymorphic-entity tables: activities + tasks.
    activities_stmt = text(
        "UPDATE tbl_activities SET entity_id = :primary "
        "WHERE org_id = :org_id "
        "AND entity_type = 'contact' AND entity_id = :secondary"
    )
    counts["activities"] = (
        await session.execute(
            activities_stmt,
            {"org_id": org_id, "primary": primary_id, "secondary": secondary_id},
        )
    ).rowcount or 0

    tasks_stmt = text(
        "UPDATE tbl_tasks SET related_entity_id = :primary "
        "WHERE org_id = :org_id "
        "AND related_entity_type = 'contact' AND related_entity_id = :secondary"
    )
    counts["tasks"] = (
        await session.execute(
            tasks_stmt,
            {"org_id": org_id, "primary": primary_id, "secondary": secondary_id},
        )
    ).rowcount or 0

    return counts


async def list_contacts_for_export(
    session: AsyncSession,
    *,
    q: str | None,
    source: str | None,
    tag: str | None,
    assigned_to_id: uuid.UUID | None,
    custom_filters: Iterable[tuple[str, str]],
) -> list[Contact]:
    """Resolve every matching contact (no pagination) for CSV export.

    Caller is expected to have already gated on `count_contacts_filtered`
    so the result fits in memory.
    """
    filters = _build_filters(
        q=q,
        source=source,
        tag=tag,
        assigned_to_id=assigned_to_id,
        custom_filters=custom_filters,
    )
    stmt = select(Contact).order_by(Contact.created_at.desc(), Contact.id.desc())
    if filters:
        stmt = stmt.where(and_(*filters))
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


__all__ = [
    "build_contact_list_query",
    "bulk_append_tag",
    "count_contacts_filtered",
    "delete_contact_row",
    "delete_contacts_in_org",
    "find_duplicate_candidates",
    "get_contact",
    "get_contact_by_phone",
    "insert_contact",
    "is_user_active_member_of_org",
    "list_contacts_by_ids_in_org",
    "list_contacts_for_export",
    "reassign_contact_references",
]
