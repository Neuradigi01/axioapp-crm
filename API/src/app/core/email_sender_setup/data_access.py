"""Data-access helpers for the sender-setup module.

Pure CRUD — no transactions, no service imports. Every query filters
on ``org_id`` as belt-and-suspenders on top of the ``do_orm_execute``
tenant listener + RLS policy.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email_sender_setup.models import EmailSenderDomain


async def get_domain_by_id(
    session: AsyncSession, *, org_id: uuid.UUID, domain_id: uuid.UUID
) -> EmailSenderDomain | None:
    """Tenant-scoped read of one row. Returns None when missing or
    when the caller's org can't see it (RLS hides cross-tenant)."""
    result = await session.execute(
        select(EmailSenderDomain).where(
            EmailSenderDomain.id == domain_id,
            EmailSenderDomain.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def get_domain_by_name(
    session: AsyncSession, *, org_id: uuid.UUID, domain: str
) -> EmailSenderDomain | None:
    """Reverse lookup for the "already exists" 409 branch on create +
    the campaign preflight's mailbox-domain lookup."""
    result = await session.execute(
        select(EmailSenderDomain).where(
            EmailSenderDomain.org_id == org_id,
            EmailSenderDomain.domain == domain.lower().strip(),
        )
    )
    return result.scalar_one_or_none()


async def list_domains(
    session: AsyncSession, *, org_id: uuid.UUID
) -> list[EmailSenderDomain]:
    """All verified + pending domains for the org, newest first."""
    result = await session.execute(
        select(EmailSenderDomain)
        .where(EmailSenderDomain.org_id == org_id)
        .order_by(EmailSenderDomain.created_at.desc())
    )
    return list(result.scalars().all())


def add_domain(session: AsyncSession, row: EmailSenderDomain) -> EmailSenderDomain:
    """Pure add — commit belongs to the caller."""
    session.add(row)
    return row


async def delete_domain(session: AsyncSession, row: EmailSenderDomain) -> None:
    """Pure delete — commit belongs to the caller."""
    await session.delete(row)


__all__ = [
    "add_domain",
    "delete_domain",
    "get_domain_by_id",
    "get_domain_by_name",
    "list_domains",
]
