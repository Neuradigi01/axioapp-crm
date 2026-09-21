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
from typing import Any

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
            detail=("Verification refreshes are limited to once per minute per domain."),
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
    from sqlalchemy import select

    from src.app.core.campaigns.models import Campaign, CampaignStatus
    from src.app.core.email.models import EmailAccount

    conflict = (
        await session.execute(
            select(Campaign.id)
            .join(
                EmailAccount,
                EmailAccount.id == Campaign.email_account_id,
            )
            .where(
                Campaign.org_id == org_id,
                Campaign.status.in_([CampaignStatus.scheduled, CampaignStatus.running]),
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
    return await data_access.get_domain_by_name(session, org_id=org_id, domain=domain.lower())


# ---------------------------------------------------------------------------
# tasks/email-sending-domains Step 3 — service functions for the new
# ``tbl_organization_email_domains`` flow.
#
# Deliberately kept in the same module as the legacy campaigns-side
# ``create_domain`` / ``verify_domain`` above so the router only wires
# one module. The two lifecycles never share state.
# ---------------------------------------------------------------------------


import logging  # noqa: E402
import os  # noqa: E402

from src.app.core import audit  # noqa: E402
from src.app.core.email.mailgun.api_client import (  # noqa: E402
    MailgunApiClient,
)
from src.app.core.email.mailgun.api_client_errors import (  # noqa: E402
    MailgunApiError,
    MailgunProviderError,
)
from src.app.core.email_sender_setup.models import (  # noqa: E402
    VERIFICATION_STATUS_DEMOTED,
    OrganizationEmailDomain,
)
from src.app.core.email_sender_setup.schemas import (  # noqa: E402
    ClaimDomainIn,
    SendEnvelope,
)

_service_logger = logging.getLogger(__name__)


class DomainAlreadyClaimedError(Exception):
    """Raised by ``claim_domain`` when the domain string is already
    globally claimed. Router maps to 409 without revealing which org
    owns the claim.
    """


class SendNotConfiguredError(Exception):
    """Raised by ``resolve_send_envelope`` when no sender path is
    available for the org: no caller-supplied id, no default sender,
    no verified own-domain, no platform-from env var. Router at Step
    5 maps to 400 with a clear "connect a mailbox or claim a domain"
    detail.
    """


def _extract_verdicts(records: list[dict[str, Any]]) -> tuple[bool, bool, bool, bool]:
    """Aggregate individual DnsRecord ``valid`` verdicts into the four
    domain-level booleans the row + response schema carry.

    Rules:
      * SPF = the one TXT record with ``v=spf1`` in its value.
      * DKIM = TXT records whose name starts with ``smtp._domainkey``
        or similar ``_domainkey`` labels — at least one must be valid.
      * DMARC = TXT record on ``_dmarc.<domain>``.
      * MX = any MX record in the receiving array valid.
    """
    spf = dkim = dmarc = mx = False
    for r in records:
        rtype = (r.get("record_type") or "").upper()
        name = (r.get("name") or "").lower()
        value = (r.get("value") or "").lower()
        valid = (r.get("valid") or "").lower() == "valid"
        if not valid:
            continue
        if rtype == "TXT":
            if "v=spf1" in value:
                spf = True
            elif "_domainkey" in name:
                dkim = True
            elif name.startswith("_dmarc"):
                dmarc = True
        elif rtype == "MX":
            mx = True
    return mx, spf, dkim, dmarc


def _all_records_valid(records_by_kind: dict[str, list[dict[str, Any]]]) -> bool:
    """True iff every DnsRecord in both sending + receiving arrays has
    ``valid == "valid"``. Any ``unknown``, ``invalid``, or missing
    verdict counts as fail."""
    total = 0
    valid = 0
    for arr in records_by_kind.values():
        for r in arr:
            total += 1
            if (r.get("valid") or "").lower() == "valid":
                valid += 1
    return total > 0 and valid == total


async def claim_domain(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payload: ClaimDomainIn,
    client: MailgunApiClient | None = None,
) -> OrganizationEmailDomain:
    """Register a new sending domain against Mailgun + persist the row.

    Sequence:
      1. Global uniqueness check (409 if any org already owns this domain).
      2. ``client.create_domain()`` — returns Mailgun's parsed shape.
      3. INSERT with ``verification_status='pending'`` + Mailgun's
         DNS records stored verbatim in the JSONB column.
      4. Audit event ``sending_domain.claimed``.

    Client injectable so tests exercise the real cascade without hitting
    Mailgun; production leaves it None and constructs from env.
    """
    domain = payload.domain
    existing_global = await data_access.find_organization_domain_by_name_global(db, domain=domain)
    if existing_global is not None:
        # Don't reveal owning org — 409 with generic detail.
        raise DomainAlreadyClaimedError(f"domain '{domain}' is already claimed")

    if client is None:
        client = MailgunApiClient(region=payload.region)
    result = await client.create_domain(domain)

    dns_records = {
        "sending": list(result.sending_dns_records),
        "receiving": list(result.receiving_dns_records),
    }
    row = OrganizationEmailDomain(
        org_id=org_id,
        domain=domain,
        mailgun_domain_id=result.mailgun_domain_id,
        dns_records=dns_records,
        region=payload.region,
    )
    data_access.add_organization_email_domain(db, row)
    await db.commit()
    await db.refresh(row)

    await audit.log(
        "sending_domain.claimed",
        entity_type="organization_email_domain",
        entity_id=row.id,
        org_id=org_id,
        user_id=actor_user_id,
        after={
            "domain": domain,
            "region": payload.region,
            "mailgun_domain_id": result.mailgun_domain_id,
        },
    )
    return row


async def verify_organization_email_domain(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
    client: MailgunApiClient | None = None,
) -> OrganizationEmailDomain:
    """Refresh a domain's verification state against Mailgun.

    Semantics:
      * All records valid → ``verification_status='verified'``,
        ``consecutive_failed_checks=0``, ``last_verified_at=now``. Fires
        one-shot notify-owner audit event on the transition ``pending →
        verified`` or ``demoted → verified``.
      * Any record fails → increments ``consecutive_failed_checks`` but
        does NOT change ``verification_status`` (Step 6 cron owns the
        demote/release transitions once counters cross threshold).
      * Mailgun provider error (5xx after retries) → propagate; caller
        surface (router: 502) plus we deliberately DO NOT bump the
        failure counter — that's transient provider blip, not DNS drift.
    """
    row = await data_access.find_organization_domain_by_id(db, id=id, org_id=org_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="domain not found",
        )

    if client is None:
        client = MailgunApiClient(region=row.region)

    try:
        detail = await client.verify_domain(row.domain)
    except MailgunProviderError:
        _service_logger.warning(
            "verify_organization_email_domain: mailgun 5xx for domain=%s id=%s "
            "(counter NOT incremented)",
            row.domain,
            row.id,
        )
        raise

    all_pass = _all_records_valid(
        {"sending": detail.sending_dns_records, "receiving": detail.receiving_dns_records}
    )
    mx, spf, dkim, dmarc = _extract_verdicts(
        list(detail.sending_dns_records) + list(detail.receiving_dns_records)
    )
    fresh_dns_records = {
        "sending": list(detail.sending_dns_records),
        "receiving": list(detail.receiving_dns_records),
    }
    prior_status = row.verification_status
    await data_access.update_verification(
        db,
        id=row.id,
        all_pass=all_pass,
        dns_records=fresh_dns_records,
        mx_verified=mx,
        spf_verified=spf,
        dkim_verified=dkim,
        dmarc_verified=dmarc,
    )

    if all_pass:
        if prior_status == VERIFICATION_STATUS_DEMOTED:
            await data_access.mark_verified_after_demotion(db, id=row.id)
        else:
            await data_access.mark_verified(db, id=row.id)

    await db.commit()
    await db.refresh(row)

    await audit.log(
        "sending_domain.verified" if all_pass else "sending_domain.verify_failed",
        entity_type="organization_email_domain",
        entity_id=row.id,
        org_id=org_id,
        user_id=actor_user_id,
        after={
            "domain": row.domain,
            "all_pass": all_pass,
            "spf_verified": spf,
            "dkim_verified": dkim,
            "dmarc_verified": dmarc,
            "mx_verified": mx,
            "prior_status": prior_status,
            "new_status": row.verification_status,
        },
    )
    return row


async def release_domain(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
    client: MailgunApiClient | None = None,
) -> None:
    """Owner-only release. Calls Mailgun DELETE, flips the row to
    ``released``, and cascades ``tbl_email_endpoint_details.domain_id``
    to NULL so any inbound endpoints that pointed at this domain go
    dormant rather than dangling.

    Idempotent w.r.t. Mailgun — a 404 there is treated as success. The
    endpoint FK cascade runs unconditionally (raw ``UPDATE ... WHERE
    domain_id = :id``) so calling ``release_domain`` twice is safe.
    """
    row = await data_access.find_organization_domain_by_id(db, id=id, org_id=org_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="domain not found",
        )

    if client is None:
        client = MailgunApiClient(region=row.region)
    try:
        await client.delete_domain(row.domain)
    except MailgunApiError as exc:
        # Non-404 provider failure — surface to caller. Row stays as-is.
        _service_logger.warning(
            "release_domain: mailgun DELETE failed for domain=%s: %s",
            row.domain,
            exc,
        )
        raise

    endpoint_rows_cleared = await data_access.null_endpoint_details_domain_fk(db, domain_id=row.id)
    await data_access.mark_released(db, id=row.id)
    await db.commit()
    await db.refresh(row)

    await audit.log(
        "sending_domain.released",
        entity_type="organization_email_domain",
        entity_id=row.id,
        org_id=org_id,
        user_id=actor_user_id,
        after={
            "domain": row.domain,
            "released_at": row.released_at.isoformat(),
            "endpoint_rows_cleared": endpoint_rows_cleared,
        },
    )


async def resolve_send_envelope(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    caller_supplied_sender_id: uuid.UUID | None = None,
) -> SendEnvelope:
    """Pick the outbound envelope for this org.

    Cascade (locked in ``README.md``): caller-supplied →
    org-default → verified own-domain → platform-from → raise
    ``SendNotConfiguredError``.

    Step 5 will refactor ``send_email()`` to consume this; for Step 3
    the function ships standalone so tests can lock the cascade
    ordering before the dispatch code touches it.
    """
    from src.app.core.email import data_access as accounts_da
    from src.app.core.email_senders import data_access as senders_da
    from src.app.shared.email.org_sender import (
        OrgOauthBackend,
        OrgSmtpBackend,
        resolve_org_sender,
    )

    # 1. Caller-supplied — look up in SMTP first, then OAuth. Same-id
    # collision across the two tables is not possible (UUIDs).
    if caller_supplied_sender_id is not None:
        smtp = await senders_da.get_by_id(db, org_id=org_id, sender_id=caller_supplied_sender_id)
        if smtp is not None:
            display = _smtp_display_from(smtp)
            return SendEnvelope(
                envelope_type="smtp_sender",
                smtp_sender_id=smtp.id,
                from_address=display,
                reply_to=smtp.from_address,
            )
        oauth = await accounts_da.get_account_by_id(db, account_id=caller_supplied_sender_id)
        if oauth is not None and oauth.org_id == org_id:
            display = _oauth_display_from(oauth)
            return SendEnvelope(
                envelope_type="oauth_account",
                oauth_account_id=oauth.id,
                from_address=display,
                reply_to=oauth.email_address,
            )
        # Explicit id given but not resolvable in caller's org — hard fail.
        raise SendNotConfiguredError(
            f"caller-supplied sender {caller_supplied_sender_id} not found in org"
        )

    # 2. Org default — reuse the shipped resolver.
    backend = await resolve_org_sender(db, org_id=org_id)
    if isinstance(backend, OrgSmtpBackend):
        display = _smtp_display_from(backend.sender)
        return SendEnvelope(
            envelope_type="smtp_sender",
            smtp_sender_id=backend.sender.id,
            from_address=display,
            reply_to=backend.sender.from_address,
        )
    if isinstance(backend, OrgOauthBackend):
        display = _oauth_display_from(backend.account)
        return SendEnvelope(
            envelope_type="oauth_account",
            oauth_account_id=backend.account.id,
            from_address=display,
            reply_to=backend.account.email_address,
        )

    # 3. Verified own-domain via Mailgun.
    own_domain = await data_access.find_verified_own_domain_for_org(db, org_id=org_id)
    if own_domain is not None:
        from_addr = f"no-reply@{own_domain.domain}"
        return SendEnvelope(
            envelope_type="own_domain",
            own_domain_id=own_domain.id,
            dispatch_domain=own_domain.domain,
            from_address=from_addr,
            reply_to=from_addr,
        )

    # 4. Platform-from fallback.
    platform_domain = os.getenv("EMAIL_PLATFORM_SENDING_DOMAIN", "").strip()
    if platform_domain:
        inbound_domain = os.getenv("INBOUND_EMAIL_DOMAIN", platform_domain).strip()
        return SendEnvelope(
            envelope_type="platform_from",
            dispatch_domain=platform_domain,
            from_address=f"org-{org_id}@{platform_domain}",
            # Step 5 wires the r-token from Track 1's endpoint model.
            # v0 placeholder: a bare no-reply on the inbound domain so
            # bounces flow to a monitored mailbox rather than /dev/null.
            reply_to=f"no-reply@{inbound_domain}",
        )

    # 5. Nothing available.
    raise SendNotConfiguredError(f"no sender path configured for org {org_id}")


def _smtp_display_from(smtp: Any) -> str:
    """``"Display Name <addr>"`` if set, else bare addr."""
    if smtp.display_name:
        return f"{smtp.display_name} <{smtp.from_address}>"
    return smtp.from_address


def _oauth_display_from(account: Any) -> str:
    if account.display_name:
        return f"{account.display_name} <{account.email_address}>"
    return account.email_address


__all__ = [
    "DomainAlreadyClaimedError",
    "SendNotConfiguredError",
    "claim_domain",
    "create_domain",
    "delete_domain",
    "dns_records_for",
    "get_domain_for_email",
    "release_domain",
    "resolve_send_envelope",
    "verify_domain",
    "verify_organization_email_domain",
]
