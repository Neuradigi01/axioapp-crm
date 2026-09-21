"""Data-access helpers for the sender-setup module.

Pure CRUD — no transactions, no service imports. Every query filters
on ``org_id`` as belt-and-suspenders on top of the ``do_orm_execute``
tenant listener + RLS policy.

Now hosts two entity classes:

  * ``EmailSenderDomain`` (legacy, campaigns-owned)
  * ``OrganizationEmailDomain`` (Track 2 sending-domains rewrite)

The two never share a helper — different semantics, different indexes,
different lifecycles.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email_sender_setup.models import (
    VERIFICATION_STATUS_DEMOTED,
    VERIFICATION_STATUS_RELEASED,
    VERIFICATION_STATUS_VERIFIED,
    EmailSenderDomain,
    OrganizationEmailDomain,
)


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


async def list_domains(session: AsyncSession, *, org_id: uuid.UUID) -> list[EmailSenderDomain]:
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


# ---------------------------------------------------------------------------
# tasks/email-sending-domains Step 3 — DAL for the new
# ``tbl_organization_email_domains`` flow.
# ---------------------------------------------------------------------------


def add_organization_email_domain(
    session: AsyncSession, row: OrganizationEmailDomain
) -> OrganizationEmailDomain:
    """Pure add — commit belongs to the caller."""
    session.add(row)
    return row


async def find_organization_domain_by_id(
    session: AsyncSession,
    *,
    id: uuid.UUID,
    org_id: uuid.UUID | None = None,
) -> OrganizationEmailDomain | None:
    """Point read. When ``org_id`` is passed the query filters
    explicitly on it (cross-org returns None); when None, RLS + the
    tenant listener still scope reads to the caller's context.
    System-actor callers (Step 6 cron) pass ``org_id=None`` and rely
    on their own row-load discipline.
    """
    stmt = select(OrganizationEmailDomain).where(OrganizationEmailDomain.id == id)
    if org_id is not None:
        stmt = stmt.where(OrganizationEmailDomain.org_id == org_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def find_organization_domain_by_name_global(
    session: AsyncSession, *, domain: str
) -> OrganizationEmailDomain | None:
    """UNSCOPED reverse lookup — used only in the claim-domain
    uniqueness check ("is this domain already claimed by ANOTHER
    org?"). Cross-org visibility here is deliberate + the caller
    surfaces a 409 rather than leaking the owning org.
    """
    result = await session.execute(
        select(OrganizationEmailDomain).where(
            OrganizationEmailDomain.domain == domain.lower().strip()
        )
    )
    return result.scalar_one_or_none()


async def find_verified_own_domain_for_org(
    session: AsyncSession, *, org_id: uuid.UUID
) -> OrganizationEmailDomain | None:
    """The org's most-recently-verified own-domain, or None. Consumed
    by the send-envelope cascade."""
    result = await session.execute(
        select(OrganizationEmailDomain)
        .where(
            OrganizationEmailDomain.org_id == org_id,
            OrganizationEmailDomain.verification_status == VERIFICATION_STATUS_VERIFIED,
        )
        .order_by(OrganizationEmailDomain.last_verified_at.desc().nulls_last())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_organization_domains_for_org(
    session: AsyncSession, *, org_id: uuid.UUID
) -> list[OrganizationEmailDomain]:
    """Every domain claim the org has made, newest first. Includes
    released rows so the frontend can render the historical timeline."""
    result = await session.execute(
        select(OrganizationEmailDomain)
        .where(OrganizationEmailDomain.org_id == org_id)
        .order_by(OrganizationEmailDomain.created_at.desc())
    )
    return list(result.scalars().all())


async def update_verification(
    session: AsyncSession,
    *,
    id: uuid.UUID,
    all_pass: bool,
    dns_records: dict[str, Any],
    mx_verified: bool,
    spf_verified: bool,
    dkim_verified: bool,
    dmarc_verified: bool,
) -> None:
    """Write the outcome of a Mailgun ``/verify`` call.

    Increments ``consecutive_failed_checks`` on any fail; zeros it +
    stamps ``last_verified_at`` on all-pass. Does NOT change
    ``verification_status`` — that's the caller's decision (a shipped
    demoted domain that goes back to all-pass stays demoted until the
    caller calls :func:`mark_verified_after_demotion`).
    """
    now = datetime.now(UTC)
    if all_pass:
        stmt = (
            update(OrganizationEmailDomain)
            .where(OrganizationEmailDomain.id == id)
            .values(
                dns_records=dns_records,
                mx_verified=mx_verified,
                spf_verified=spf_verified,
                dkim_verified=dkim_verified,
                dmarc_verified=dmarc_verified,
                last_verified_at=now,
                consecutive_failed_checks=0,
                updated_at=now,
            )
        )
    else:
        stmt = (
            update(OrganizationEmailDomain)
            .where(OrganizationEmailDomain.id == id)
            .values(
                dns_records=dns_records,
                mx_verified=mx_verified,
                spf_verified=spf_verified,
                dkim_verified=dkim_verified,
                dmarc_verified=dmarc_verified,
                consecutive_failed_checks=OrganizationEmailDomain.consecutive_failed_checks + 1,
                updated_at=now,
            )
        )
    await session.execute(stmt)


async def mark_verified(session: AsyncSession, *, id: uuid.UUID) -> None:
    """Transition ``pending → verified`` after the first all-pass
    ``/verify``. Idempotent; already-verified rows are unchanged."""
    now = datetime.now(UTC)
    await session.execute(
        update(OrganizationEmailDomain)
        .where(OrganizationEmailDomain.id == id)
        .values(
            verification_status=VERIFICATION_STATUS_VERIFIED,
            updated_at=now,
        )
    )


async def mark_demoted(session: AsyncSession, *, id: uuid.UUID) -> None:
    """Transition to demoted (Step 6 cron's threshold breach)."""
    now = datetime.now(UTC)
    await session.execute(
        update(OrganizationEmailDomain)
        .where(OrganizationEmailDomain.id == id)
        .values(
            verification_status=VERIFICATION_STATUS_DEMOTED,
            demoted_at=now,
            updated_at=now,
        )
    )


async def mark_verified_after_demotion(session: AsyncSession, *, id: uuid.UUID) -> None:
    """Recovery transition. Clears ``demoted_at``, flips status back
    to verified. Consumed by Step 6's hourly demoted-only sweep."""
    now = datetime.now(UTC)
    await session.execute(
        update(OrganizationEmailDomain)
        .where(OrganizationEmailDomain.id == id)
        .values(
            verification_status=VERIFICATION_STATUS_VERIFIED,
            demoted_at=None,
            last_verified_at=now,
            consecutive_failed_checks=0,
            updated_at=now,
        )
    )


async def mark_released(session: AsyncSession, *, id: uuid.UUID) -> None:
    """Terminal state — the domain is gone from Mailgun's side.
    Preserves the row for audit; ``verification_status='released'``
    keeps it out of the send cascade forever."""
    now = datetime.now(UTC)
    await session.execute(
        update(OrganizationEmailDomain)
        .where(OrganizationEmailDomain.id == id)
        .values(
            verification_status=VERIFICATION_STATUS_RELEASED,
            released_at=now,
            updated_at=now,
        )
    )


async def null_endpoint_details_domain_fk(session: AsyncSession, *, domain_id: uuid.UUID) -> int:
    """Set ``tbl_email_endpoint_details.domain_id = NULL`` for every row
    referencing this domain. Returns the row count.

    The FK is unconstrained at the ORM level (Track 1 keeps it nullable
    + unconstrained to avoid a cyclic migration dep on Track 2's table).
    Raw ``UPDATE`` — no ORM instance materialised — so cascade cost is
    O(matching rows) regardless of how many endpoint rows exist for the
    org.
    """
    result = await session.execute(
        sql_text(
            "UPDATE tbl_email_endpoint_details SET domain_id = NULL WHERE domain_id = :domain_id"
        ),
        {"domain_id": domain_id},
    )
    return result.rowcount or 0


__all__ = [
    "add_domain",
    "add_organization_email_domain",
    "delete_domain",
    "find_organization_domain_by_id",
    "find_organization_domain_by_name_global",
    "find_verified_own_domain_for_org",
    "get_domain_by_id",
    "get_domain_by_name",
    "list_domains",
    "list_organization_domains_for_org",
    "mark_demoted",
    "mark_released",
    "mark_verified",
    "mark_verified_after_demotion",
    "null_endpoint_details_domain_fk",
    "update_verification",
]
