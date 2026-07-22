"""Pure CRUD helpers for the ``tbl_email_smtp_senders`` table.

Belongs to the Router → Service → DAL contract: no transactions, no
business logic, no imports from :mod:`service` or :mod:`router`. Every
query filters explicitly on ``org_id`` on top of the shared tenant
listener + RLS policy.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email_senders.models import EmailSmtpSender


def add_sender(session: AsyncSession, row: EmailSmtpSender) -> EmailSmtpSender:
    """Stage an INSERT — commit belongs to the caller."""
    session.add(row)
    return row


async def get_by_id(
    session: AsyncSession, *, org_id: uuid.UUID, sender_id: uuid.UUID
) -> EmailSmtpSender | None:
    """Tenant-scoped point read. Returns None on miss / cross-tenant."""
    result = await session.execute(
        select(EmailSmtpSender).where(
            EmailSmtpSender.id == sender_id,
            EmailSmtpSender.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def list_smtp_senders(
    session: AsyncSession, *, org_id: uuid.UUID
) -> list[EmailSmtpSender]:
    """All SMTP senders (verified + pending) for the org, newest first."""
    result = await session.execute(
        select(EmailSmtpSender)
        .where(EmailSmtpSender.org_id == org_id)
        .order_by(EmailSmtpSender.created_at.desc())
    )
    return list(result.scalars().all())


async def find_by_org_and_from(
    session: AsyncSession, *, org_id: uuid.UUID, from_address: str
) -> EmailSmtpSender | None:
    """Reverse lookup for the "already exists" 409 branch on create."""
    result = await session.execute(
        select(EmailSmtpSender).where(
            EmailSmtpSender.org_id == org_id,
            EmailSmtpSender.from_address == from_address.lower(),
        )
    )
    return result.scalar_one_or_none()


async def find_default_verified(
    session: AsyncSession, *, org_id: uuid.UUID
) -> EmailSmtpSender | None:
    """The org's ``is_default=True`` verified SMTP sender, or None."""
    result = await session.execute(
        select(EmailSmtpSender).where(
            EmailSmtpSender.org_id == org_id,
            EmailSmtpSender.is_default.is_(True),
            EmailSmtpSender.verified_at.is_not(None),
        )
    )
    return result.scalar_one_or_none()


async def find_any_verified(
    session: AsyncSession, *, org_id: uuid.UUID
) -> EmailSmtpSender | None:
    """Any verified SMTP sender for the org — used as the fallback in
    :func:`shared.email.org_sender.resolve_org_sender` when no default
    is set."""
    result = await session.execute(
        select(EmailSmtpSender)
        .where(
            EmailSmtpSender.org_id == org_id,
            EmailSmtpSender.verified_at.is_not(None),
        )
        .order_by(EmailSmtpSender.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def count_verified(session: AsyncSession, *, org_id: uuid.UUID) -> int:
    """How many verified SMTP senders the org has. Used by
    :func:`service.verify_smtp_sender` to decide whether to auto-flip
    ``is_default`` on the first one."""
    from sqlalchemy import func

    result = await session.execute(
        select(func.count()).select_from(
            select(EmailSmtpSender)
            .where(
                EmailSmtpSender.org_id == org_id,
                EmailSmtpSender.verified_at.is_not(None),
            )
            .subquery()
        )
    )
    return int(result.scalar_one() or 0)


def mark_verified(row: EmailSmtpSender, *, when) -> None:
    """Mutate the row in-place: stamp verified_at + clear the code
    columns. Caller commits."""
    row.verified_at = when
    row.verification_code_hash = None
    row.verification_expires_at = None


async def clear_all_defaults(
    session: AsyncSession, *, org_id: uuid.UUID
) -> None:
    """Reset ``is_default=false`` on every SMTP sender in the org.
    Caller commits — used as the first half of the ``set_default``
    flip so the resulting state has exactly one default row."""
    await session.execute(
        update(EmailSmtpSender)
        .where(EmailSmtpSender.org_id == org_id)
        .values(is_default=False)
    )


def set_default(row: EmailSmtpSender) -> None:
    """Mutate the row in-place: ``is_default=True``. Caller commits."""
    row.is_default = True


async def delete_by_id(
    session: AsyncSession, *, org_id: uuid.UUID, sender_id: uuid.UUID
) -> bool:
    """Delete one sender. Returns True on hit, False on miss. Caller
    commits."""
    row = await get_by_id(session, org_id=org_id, sender_id=sender_id)
    if row is None:
        return False
    await session.delete(row)
    return True


__all__ = [
    "add_sender",
    "clear_all_defaults",
    "count_verified",
    "delete_by_id",
    "find_any_verified",
    "find_by_org_and_from",
    "find_default_verified",
    "get_by_id",
    "list_smtp_senders",
    "mark_verified",
    "set_default",
]
