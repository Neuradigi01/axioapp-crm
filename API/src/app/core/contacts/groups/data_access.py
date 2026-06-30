"""Data-access layer for contact-groups CRUD + audience resolution.

Pure query helpers — no transactions, no audit. Leaf module; never
imports a `service.py`.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from src.app.core.contacts.groups.models import (
    ContactGroup,
    ContactGroupMember,
)
from src.app.core.contacts.models import Contact


def _build_contact_filter_predicates(
    filter_json: dict[str, Any] | None,
) -> list[ColumnElement[bool]]:
    """Translate a `{q, source, tag}` shape into SQLAlchemy WHERE
    predicates. Same rules the contacts list endpoint uses; kept
    duplicated rather than imported to avoid a service-layer
    dependency cycle (contacts → groups → contacts)."""
    filters: list[ColumnElement[bool]] = []
    if not filter_json:
        return filters
    q = filter_json.get("q")
    if q:
        like = f"%{q}%"
        filters.append(
            or_(
                Contact.full_name.ilike(like),
                Contact.phone.ilike(like),
                Contact.email.ilike(like),
            )
        )
    source = filter_json.get("source")
    if source:
        filters.append(Contact.source == source)
    tag = filter_json.get("tag")
    if tag:
        filters.append(Contact.tags.contains([tag]))
    return filters


async def get_group_by_id(session: AsyncSession, group_id: uuid.UUID) -> ContactGroup | None:
    """Single group lookup — caller raises 404."""
    result = await session.execute(select(ContactGroup).where(ContactGroup.id == group_id))
    return result.scalar_one_or_none()


async def count_groups(session: AsyncSession) -> int:
    """Total contact-groups count (auto-tenant-scoped)."""
    result = await session.execute(select(func.count()).select_from(ContactGroup))
    return int(result.scalar_one())


async def list_groups_page(session: AsyncSession, *, offset: int, limit: int) -> list[ContactGroup]:
    """Page of contact-groups sorted newest-first."""
    rows = (
        (
            await session.execute(
                select(ContactGroup)
                .order_by(ContactGroup.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


def add_group(session: AsyncSession, group: ContactGroup) -> ContactGroup:
    """Stage a new contact-group row in the unit-of-work."""
    session.add(group)
    return group


async def delete_group_row(session: AsyncSession, group: ContactGroup) -> None:
    """Hard-delete a contact-group row (member rows CASCADE)."""
    await session.delete(group)


async def delete_members_for_group(session: AsyncSession, group_id: uuid.UUID) -> None:
    """Drop every member row for one group — used by full-replace update."""
    await session.execute(
        ContactGroupMember.__table__.delete().where(ContactGroupMember.group_id == group_id)
    )


async def bulk_upsert_members(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    group_id: uuid.UUID,
    contact_ids: list[uuid.UUID],
) -> None:
    """Idempotent bulk member insert.

    `ON CONFLICT DO NOTHING` on `(group_id, contact_id)` means a
    retried setter does not duplicate rows.
    """
    if not contact_ids:
        return
    rows = [{"org_id": org_id, "group_id": group_id, "contact_id": cid} for cid in contact_ids]
    await session.execute(
        pg_insert(ContactGroupMember)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["group_id", "contact_id"])
    )


async def list_contact_ids_matching_filter(
    session: AsyncSession,
    *,
    filter_json: dict[str, Any] | None,
) -> list[uuid.UUID]:
    """Dynamic-group resolver: contacts matching a `{q, source, tag}` filter."""
    predicates = _build_contact_filter_predicates(filter_json)
    stmt = select(Contact.id)
    if predicates:
        stmt = stmt.where(and_(*predicates))
    stmt = stmt.order_by(Contact.id)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def list_static_member_contact_ids(
    session: AsyncSession, group_id: uuid.UUID
) -> list[uuid.UUID]:
    """Static-group resolver: `tbl_contact_group_members.contact_id` rows."""
    rows = (
        (
            await session.execute(
                select(ContactGroupMember.contact_id)
                .where(ContactGroupMember.group_id == group_id)
                .order_by(ContactGroupMember.contact_id)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def count_contacts_matching_filter(
    session: AsyncSession,
    *,
    filter_json: dict[str, Any] | None,
) -> int:
    """Cheap COUNT for the dynamic preview / member-count read."""
    predicates = _build_contact_filter_predicates(filter_json)
    stmt = select(func.count()).select_from(Contact)
    if predicates:
        stmt = stmt.where(and_(*predicates))
    return int((await session.execute(stmt)).scalar_one())


async def count_static_members(session: AsyncSession, group_id: uuid.UUID) -> int:
    """Member count for a static group."""
    result = await session.execute(
        select(func.count())
        .select_from(ContactGroupMember)
        .where(ContactGroupMember.group_id == group_id)
    )
    return int(result.scalar_one())


async def list_contact_ids_matching_filter_limited(
    session: AsyncSession,
    *,
    filter_json: dict[str, Any] | None,
    limit: int,
) -> list[uuid.UUID]:
    """First `limit` dynamic-group hits for the detail-page sample."""
    predicates = _build_contact_filter_predicates(filter_json)
    stmt = select(Contact.id).order_by(Contact.id).limit(limit)
    if predicates:
        stmt = stmt.where(and_(*predicates))
    return list((await session.execute(stmt)).scalars().all())


async def list_static_member_contact_ids_limited(
    session: AsyncSession, group_id: uuid.UUID, *, limit: int
) -> list[uuid.UUID]:
    """First `limit` static-group hits for the detail-page sample."""
    rows = (
        (
            await session.execute(
                select(ContactGroupMember.contact_id)
                .where(ContactGroupMember.group_id == group_id)
                .order_by(ContactGroupMember.contact_id)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


__all__ = [
    "add_group",
    "bulk_upsert_members",
    "count_contacts_matching_filter",
    "count_groups",
    "count_static_members",
    "delete_group_row",
    "delete_members_for_group",
    "get_group_by_id",
    "list_contact_ids_matching_filter",
    "list_contact_ids_matching_filter_limited",
    "list_groups_page",
    "list_static_member_contact_ids",
    "list_static_member_contact_ids_limited",
]
