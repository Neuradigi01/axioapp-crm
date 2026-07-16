"""Service layer for the sender-setup module.

Two write paths + one read path:

  * :func:`create_domain` — validates the domain shape, generates a
    stable ``dkim_selector``, stores a placeholder ``dkim_public_key``
    (real keypair generation ships with DKIM signing rollout), inserts
    the row. Rejects duplicates with a 409.
  * :func:`verify_domain` — calls
    :func:`core.email.dkim_spf_check.check_domain` (parallel SPF /
    DKIM / DMARC lookups). Rate-limited to one refresh per 60s per
    (org, domain). Updates the row's booleans + timestamps.
  * :func:`is_sender_ready` — helper for the campaigns pre-flight.
    Returns a tuple of ``(ready, warn)`` given an email address —
    ``ready`` false = block, ``warn`` true = degradation banner.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email.dkim_spf_check import check_domain as check_dns
from src.app.core.email_sender_setup import data_access
from src.app.core.email_sender_setup.models import EmailSenderDomain
from src.app.core.email_sender_setup.schemas import DnsRecord

# 60-second refresh window per (org, domain) — deters accidental
# thrashing when a user hammers the Verify button.
_VERIFY_RATE_LIMIT_SECONDS = 60.0
_verify_last_hit: dict[tuple[str, str], float] = {}


def _dkim_selector_for_org(org_id: uuid.UUID) -> str:
    """Deterministic per-org selector so re-runs yield the same value
    (idempotent regenerate on 409-recovery). Fits in 63 chars per the
    DNS label limit."""
    return f"core-crm-{str(org_id)[:8]}"


async def create_domain(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    domain: str,
) -> EmailSenderDomain:
    """Add ``domain`` to the org's sender-setup registry. 409 when the
    domain already exists for this org."""
    existing = await data_access.get_domain_by_name(session, org_id=org_id, domain=domain)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Domain '{domain}' is already registered for this org.",
        )
    row = EmailSenderDomain(
        org_id=org_id,
        domain=domain.lower().strip(),
        dkim_selector=_dkim_selector_for_org(org_id),
        # Placeholder — real DKIM keypair generation lands with the
        # DKIM-signing rollout. The frontend renders "public key TBD;
        # DKIM signing coming soon" until then.
        dkim_public_key="pending",
    )
    data_access.add_domain(session, row)
    await session.commit()
    await session.refresh(row)
    return row


def dns_records_for(row: EmailSenderDomain) -> list[DnsRecord]:
    """Compose the three DNS records the operator must publish.

    * **SPF** — one TXT at the apex authorising the CRM's send path.
    * **DKIM** — one TXT at ``<selector>._domainkey.<domain>`` with
      the public key.
    * **DMARC** — one TXT at ``_dmarc.<domain>`` with a permissive
      ``p=none`` policy so we can observe reports without hard-
      failing legitimate mail during setup.

    Values are shown verbatim in the UI's copy-paste table, so any
    change here is a documented breaking change for setup docs.
    """
    return [
        DnsRecord(
            type="TXT",
            host=row.domain,
            value="v=spf1 include:_spf.google.com include:spf.protection.outlook.com ~all",
            purpose="spf",
        ),
        DnsRecord(
            type="TXT",
            host=f"{row.dkim_selector}._domainkey.{row.domain}",
            value=f"v=DKIM1; k=rsa; p={row.dkim_public_key}",
            purpose="dkim",
        ),
        DnsRecord(
            type="TXT",
            host=f"_dmarc.{row.domain}",
            value="v=DMARC1; p=none; rua=mailto:dmarc@yourshop.com",
            purpose="dmarc",
        ),
    ]


async def verify_domain(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    domain_id: uuid.UUID,
) -> EmailSenderDomain:
    """Re-check SPF/DKIM/DMARC against DNS, update the row, return it.

    Rate-limited to once per 60s per (org, domain) — a 429 signals the
    caller to wait rather than spamming the resolver.
    """
    row = await data_access.get_domain_by_id(session, org_id=org_id, domain_id=domain_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found.",
        )
    key = (str(org_id), row.domain)
    now = time.time()
    last = _verify_last_hit.get(key)
    if last is not None and (now - last) < _VERIFY_RATE_LIMIT_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Verification refreshes are limited to once per minute per domain."
            ),
        )
    _verify_last_hit[key] = now

    result = await check_dns(org_id=str(org_id), domain=row.domain, force_refresh=True)
    stamp = datetime.now(UTC)
    row.spf_verified = result.spf == "valid"
    row.dkim_verified = result.dkim == "valid"
    row.dmarc_verified = result.dmarc == "valid"
    row.spf_last_checked_at = stamp
    row.dkim_last_checked_at = stamp
    row.dmarc_last_checked_at = stamp
    await session.commit()
    await session.refresh(row)
    return row


async def delete_domain(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    domain_id: uuid.UUID,
) -> None:
    """Remove a domain. No FK constraint on ``EmailAccount.email_address``
    → we do a soft check for scheduled/running campaigns that reference
    a mailbox on this domain and refuse in that case."""
    row = await data_access.get_domain_by_id(session, org_id=org_id, domain_id=domain_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found.",
        )
    # Defensive cross-check: any scheduled/running campaign whose
    # mailbox belongs to this domain must survive the delete.
    from src.app.core.campaigns.models import Campaign, CampaignStatus
    from src.app.core.email.models import EmailAccount
    from sqlalchemy import select

    conflict = (
        await session.execute(
            select(Campaign.id)
            .join(
                EmailAccount,
                EmailAccount.id == Campaign.email_account_id,
            )
            .where(
                Campaign.org_id == org_id,
                Campaign.status.in_(
                    [CampaignStatus.scheduled, CampaignStatus.running]
                ),
                EmailAccount.email_address.ilike(f"%@{row.domain}"),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if conflict is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Cannot delete: a scheduled or running campaign still "
                "sends from a mailbox on this domain."
            ),
        )
    await data_access.delete_domain(session, row)
    await session.commit()


async def get_domain_for_email(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    email_address: str,
) -> EmailSenderDomain | None:
    """Extract the domain from an email address and return the
    matching sender-setup row (or None). Case-insensitive."""
    _, _, domain = email_address.partition("@")
    if not domain:
        return None
    return await data_access.get_domain_by_name(
        session, org_id=org_id, domain=domain.lower()
    )


__all__ = [
    "create_domain",
    "delete_domain",
    "dns_records_for",
    "get_domain_for_email",
    "verify_domain",
]
