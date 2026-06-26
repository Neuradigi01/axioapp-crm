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
from typing import Any, Iterable

from sqlalchemy import (
    and_,
    delete as sa_delete,
    func,
    or_,
    select,
    update as sa_update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, Select

from src.app.core.contacts.models import Contact
from src.app.core.users.models import OrganizationMember, User


async def get_contact(
    session: AsyncSession, contact_id: uuid.UUID
) -> Contact | None:
    """Resolve a contact by its UUID PK.

    Tenant scoping is applied automatically by the `do_orm_execute`
    listener (Contact is `TenantScoped`), so the row is only returned
    when it belongs to the active request's org. Callers that run
    outside a tenant context (Celery, scripts) must set
    `RequestContext.org_id` first.
    """
    result = await session.execute(
        select(Contact).where(Contact.id == contact_id)
    )
    return result.scalar_one_or_none()


async def get_contact_by_phone(
    session: AsyncSession, phone: str
) -> Contact | None:
    """Resolve a contact by phone number.

    Used by walk-in reception (existing-customer detection) and by
    the conversation router (inbound WhatsApp / SMS → contact mapping).
    The phone column is indexed but not unique — multiple contacts
    can share a number across orgs (different tenants). The tenant
    auto-filter narrows the result to the active org.
    """
    result = await session.execute(
        select(Contact).where(Contact.phone == phone)
    )
    return result.scalar_one_or_none()


def insert_contact(session: AsyncSession, contact: Contact) -> None:
    """Register an already-constructed Contact for INSERT. Caller
    commits or flushes. Used by webhook intake paths that need to
    materialise a placeholder contact for an unknown phone number
    (conversations, walk-ins)."""
    session.add(contact)


async def delete_contact_row(
    session: AsyncSession, contact: Contact
) -> None:
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
            sort_column.asc().nulls_last()
            if order == "asc"
            else sort_column.desc().nulls_last()
        )
    else:
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
            func.regexp_replace(Contact.phone, r"\D", "", "g").like(
                f"%{phone_suffix}"
            )
        )
    if email_lower:
        or_filters.append(func.lower(Contact.email) == email_lower)
    if not or_filters:
        return []
    stmt = (
        select(Contact)
        .where(Contact.org_id == org_id)
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
    stmt = select(Contact).order_by(
        Contact.created_at.desc(), Contact.id.desc()
    )
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
    "list_contacts_for_export",
]
