"""Data-access layer for contact bulk imports."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.contacts.groups.models import (
    ContactGroup,
    ContactGroupMember,
)
from src.app.core.contacts.imports.models import ContactImport
from src.app.core.contacts.models import Contact


async def get_import_by_id(session: AsyncSession, import_id: uuid.UUID) -> ContactImport | None:
    """Single import row lookup — caller raises 404."""
    result = await session.execute(select(ContactImport).where(ContactImport.id == import_id))
    return result.scalar_one_or_none()


def add_import(session: AsyncSession, row: ContactImport) -> ContactImport:
    """Stage a new `tbl_contact_imports` row in the unit-of-work."""
    session.add(row)
    return row


def add_contact(session: AsyncSession, contact: Contact) -> Contact:
    """Stage a new `tbl_contacts` row in the unit-of-work."""
    session.add(contact)
    return contact


def add_group(session: AsyncSession, group: ContactGroup) -> ContactGroup:
    """Stage a new `tbl_contact_groups` row for the "create group on
    import" path."""
    session.add(group)
    return group


async def bulk_upsert_group_members(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    group_id: uuid.UUID,
    contact_ids: list[uuid.UUID],
) -> None:
    """Idempotent bulk membership insert for newly-imported contacts."""
    if not contact_ids:
        return
    await session.execute(
        pg_insert(ContactGroupMember)
        .values(
            [
                {
                    "org_id": org_id,
                    "group_id": group_id,
                    "contact_id": cid,
                }
                for cid in contact_ids
            ]
        )
        .on_conflict_do_nothing(index_elements=["group_id", "contact_id"])
    )


async def list_matching_phones_by_suffix(
    session: AsyncSession, *, suffixes: list[str]
) -> list[str]:
    """Return only those contact phones whose digit-only tail matches
    one of the last-10-digit ``suffixes`` from an incoming import.

    Replaces the old ``list_all_non_null_phones`` which streamed every
    phone in the tenant. ``regexp_replace(phone, '\\D', '', 'g')``
    strips non-digits, ``LIKE '%<suf>'`` matches the tail. Empty
    ``suffixes`` returns ``[]`` without a round-trip."""
    if not suffixes:
        return []
    digits_only = func.regexp_replace(Contact.phone, r"\D", "", "g")
    predicates = [digits_only.like(f"%{s}") for s in suffixes if s]
    if not predicates:
        return []
    rows = (
        (
            await session.execute(
                select(Contact.phone)
                .where(Contact.phone.is_not(None))
                .where(or_(*predicates))
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


__all__ = [
    "add_contact",
    "add_group",
    "add_import",
    "bulk_upsert_group_members",
    "get_import_by_id",
    "list_matching_phones_by_suffix",
]
