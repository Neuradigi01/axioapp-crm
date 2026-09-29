"""Service layer for the campaigns engine.

Four concerns:



1. CRUD over `Campaign`. Mutations restricted to `status='draft'` —
   once a campaign starts, name/template/audience are frozen.
2. `enqueue` — resolves the audience filter into a list of contact
   ids, splits into chunks of `CHUNK_SIZE`, and dispatches one Celery
   task per chunk. With `CELERY_ENABLED=false` (dev default), tasks
   run eagerly in-process so the verification path stays simple.
3. `dispatch_chunk` — the actual sender, called from the Celery task.
   Per contact: find-or-create the conversation, call the registered
   channel adapter's `send()`, persist a `CampaignMessage` row.
4. Stats — aggregate count by `CampaignMessage.status`.

Audience resolution reuses the same filter shape as `/contacts` so
the engine doesn't reinvent query semantics.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.campaigns import data_access as campaigns_da
from src.app.core.campaigns.models import (
    Campaign,
    CampaignMessage,
    CampaignMessageStatus,
    CampaignStatus,
)
from src.app.core.campaigns.schemas import (
    AudienceFilter,
    CampaignCreate,
    CampaignUpdate,
)
from src.app.core.campaigns.utils import (
    render_body,
    render_subject,
)
from src.app.core.contacts import service as contacts_service
from src.app.core.contacts.models import Contact
from src.app.core.conversations.adapters import ChannelMessageRef
from src.app.core.conversations.adapters.whatsapp import (
    WhatsAppNotConnected,
    WhatsAppRateLimited,
    resolve_whatsapp_adapter,
)
from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    Message,
    MessageDirection,
)
from src.app.core.conversations.registry import (
    ChannelNotRegistered,
)
from src.app.core.conversations.registry import (
    resolve as resolve_channel,
)
from src.app.core.email import data_access as email_da
from src.app.core.email.models import EmailAccount, EmailAccountSyncState
from src.app.core.email_senders.models import EmailSmtpSender
from src.app.core.integrations.whatsapp.models import WhatsAppTemplate
from src.app.core.templates.sanitizer import (
    derive_plain_text,
    sanitize_email_html,
)
from src.app.core.tenants.models import Organization
from src.app.shared.audit import log_entity_change, snapshot
from src.app.shared.db.queries import ensure_found, get_or_404

logger = logging.getLogger(__name__)

CHUNK_SIZE = 50


# --- reads ---------------------------------------------------------------


async def list_campaigns(
    session: AsyncSession,
    *,
    page: int = 1,
    size: int = 50,
    include_archived: bool = False,
    archived_only: bool = False,
) -> tuple[list[Campaign], int]:
    """List campaigns, defaulting to the non-archived subset.

    ``include_archived=True`` widens to include soft-archived rows;
    ``archived_only=True`` narrows to ONLY archived rows (Archived
    filter chip). The total is per-scope, so pagination on the
    Archived tab counts correctly.
    """
    from sqlalchemy import func, select

    stmt = select(func.count()).select_from(Campaign)
    if archived_only:
        stmt = stmt.where(Campaign.archived_at.is_not(None))
    elif not include_archived:
        stmt = stmt.where(Campaign.archived_at.is_(None))
    total = int((await session.execute(stmt)).scalar_one())
    offset = (page - 1) * size
    rows = await campaigns_da.list_campaigns_page(
        session,
        offset=offset,
        limit=size,
        include_archived=include_archived,
        archived_only=archived_only,
    )
    return rows, total


async def get_campaign(session: AsyncSession, campaign_id: uuid.UUID) -> Campaign:
    return await get_or_404(session, Campaign, campaign_id, entity="campaign")


# --- writes --------------------------------------------------------------


async def _resolve_email_sender(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    account_id: uuid.UUID,
) -> EmailAccount:
    """Campaigns v1 Step 03 — verify the requested Email mailbox exists
    in this org and is currently connected. The lookup goes through
    the email module's DAL (a plain read, no business rule beyond the
    tenant filter), and this function owns the availability check +
    error mapping. Called from ``create_campaign`` / ``update_campaign``
    when either ``channel == email`` at create time or the caller is
    swapping the mailbox on a Draft.

    Returns the row so the caller can persist it directly; raises 400
    when the mailbox isn't visible in this org (RLS hides cross-tenant
    rows and the DAL returns None) or when it isn't in the ``live``
    sync state (a disconnected / erroring mailbox can't dispatch).
    """
    account = await email_da.get_account_by_id(session, account_id=account_id)
    if account is None or account.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email account not found or belongs to another org.",
        )
    if account.sync_state != EmailAccountSyncState.live:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Selected mailbox is not connected — reconnect it in "
                "Email Sender Setup and try again."
            ),
        )
    return account


async def _resolve_smtp_sender(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    sender_id: uuid.UUID,
) -> EmailSmtpSender:
    """Migration-0213 companion to :func:`_resolve_email_sender` — verify
    the requested SMTP sender identity exists in this org and has been
    verified (``verified_at`` stamped). Returns the row so callers can
    persist ``smtp_sender_id`` on the campaign; raises 400 when the row
    is missing, cross-org, or still awaiting the 6-digit code from
    ``core/email_senders/verify_smtp_sender``.
    """
    from src.app.core.email_senders import data_access as smtp_da

    sender = await smtp_da.get_by_id(session, org_id=org_id, sender_id=sender_id)
    if sender is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SMTP sender not found or belongs to another org.",
        )
    if sender.verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Selected SMTP sender is not verified — enter the 6-digit code from "
                "the verification email in Integrations → Email Sender first."
            ),
        )
    return sender


async def _check_email_sender_readiness(
    session: AsyncSession,
    *,
    campaign: Campaign,
) -> list[str]:
    """Campaigns v1 Step 07 — sender-readiness pre-flight for Email
    campaigns. Reads the ``require_full_domain_verification`` flag on
    ``OrgSettings``; a fully-verified domain sails through, a partially-
    verified one warns (returned as a list the caller can attach to the
    audit event / campaign warnings) unless the strict flag is set, in
    which case we hard-block with a 400.

    Domains that haven't been registered in Email Sender Setup at all
    are treated the same as unverified — a fresh install has no
    domains yet, so the default behaviour must be "warn, not block"
    or we'd trap the user's very first campaign.
    """
    from sqlalchemy import select

    from src.app.core.email_sender_setup.service import get_domain_for_email
    from src.app.core.settings.models import OrgSettings

    if campaign.email_account_id is None:
        return []

    account = await email_da.get_account_by_id(session, account_id=campaign.email_account_id)
    if account is None:
        # Step 03's _resolve_email_sender already rejected this case at
        # create time. If it survived until enqueue it means the mailbox
        # was deleted between save and start; surface as a hard block.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sender mailbox no longer exists.",
        )
    if account.sync_state != EmailAccountSyncState.live:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Selected mailbox is not connected — reconnect it in Email Sender Setup and retry."
            ),
        )

    org_settings = (
        await session.execute(select(OrgSettings).where(OrgSettings.org_id == campaign.org_id))
    ).scalar_one_or_none()
    strict = bool(org_settings is not None and org_settings.require_full_domain_verification)

    sender_domain = await get_domain_for_email(
        session, org_id=campaign.org_id, email_address=account.email_address
    )
    warnings: list[str] = []
    if sender_domain is None:
        note = (
            f"Sender domain of {account.email_address} isn't set up in "
            "Email Sender Setup — deliverability may suffer."
        )
    elif not sender_domain.fully_verified:
        missing = [
            k
            for k, v in (
                ("SPF", sender_domain.spf_verified),
                ("DKIM", sender_domain.dkim_verified),
                ("DMARC", sender_domain.dmarc_verified),
            )
            if not v
        ]
        note = (
            f"Sender domain {sender_domain.domain} is missing: "
            f"{', '.join(missing)}. Deliverability may suffer."
        )
    else:
        return []

    if strict:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                note + " Complete DKIM / SPF / DMARC in Email Sender "
                "Setup or disable ``require_full_domain_verification`` "
                "in Settings."
            ),
        )
    warnings.append(note)
    return warnings


async def _suppress_bounced_contacts(
    session: AsyncSession,
    *,
    campaign: Campaign,
    contact_ids: list[uuid.UUID],
) -> tuple[list[uuid.UUID], int]:
    """Filter ``contact_ids`` to exclude any whose email address has
    a hard-bounce / spam-complaint record on file.

    Two queries: one to fetch (contact_id, email) for the campaign's
    audience, and one to load the org's hard-bounce email set. Cheap
    even at 10k contacts because the join predicate stays on indexed
    ``contact.email`` + the bounce table's ``email_address`` column."""
    from sqlalchemy import select

    from src.app.core.automation.models import EmailBounceEvent
    from src.app.core.contacts.models import Contact

    if not contact_ids:
        return contact_ids, 0

    contacts_rows = (
        await session.execute(select(Contact.id, Contact.email).where(Contact.id.in_(contact_ids)))
    ).all()
    email_by_contact = {row[0]: (row[1] or "").lower() for row in contacts_rows if row[1]}

    bounced_emails = {
        row[0].lower()
        for row in (
            await session.execute(
                select(EmailBounceEvent.email_address).where(
                    EmailBounceEvent.org_id == campaign.org_id,
                    EmailBounceEvent.bounce_type.in_(["hard", "complaint"]),
                )
            )
        ).all()
        if row[0]
    }

    keep: list[uuid.UUID] = []
    excluded = 0
    for cid in contact_ids:
        email = email_by_contact.get(cid)
        if email and email in bounced_emails:
            excluded += 1
        else:
            keep.append(cid)
    return keep, excluded


async def check_readiness(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
) -> dict[str, Any]:
    """Campaigns v1 Step 07c — pre-flight readiness inspector.

    Returns a structured report the wizard + list-page Start button
    surface BEFORE calling ``enqueue``, so the operator learns about
    the "org has no postal address" / "audience has 0 eligible
    contacts" gaps up-front instead of watching every queued message
    fail during dispatch.

    Shape::

        {
            "campaign_id": ...,
            "channel": "whatsapp" | "email",
            "audience_size": N,
            "eligible_count": N,       # audience minus opt-out / bounced / no-email
            "excluded_opted_out": N,
            "excluded_no_email": N,    # Email only
            "excluded_bounced": N,     # Email only, hard/complaint bounces
            "blockers": [{"code": ..., "message": ...}],
            "warnings": [{"code": ..., "message": ...}],
        }

    A non-empty ``blockers`` list means ``enqueue`` will 400; the
    wizard uses this to disable the Start button + link the user to
    the fix (Settings → Store Profile / Sender Setup / Email Accounts).
    """
    from sqlalchemy import select

    from src.app.core.email.tracking import footer as tracking_footer
    from src.app.core.settings.models import OrgSettings

    campaign = await get_campaign(session, campaign_id)
    is_email = campaign.channel == ConversationChannel.email

    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    # Audience resolution — same call ``enqueue`` uses, so the count
    # the wizard shows matches what the start endpoint acts on.
    contact_ids = await resolve_audience(session, audience_filter=campaign.audience_filter)
    audience_size = len(contact_ids)

    excluded_opted_out = 0
    excluded_no_email = 0
    excluded_bounced = 0
    eligible = audience_size

    if audience_size == 0:
        blockers.append(
            {
                "code": "empty_audience",
                "message": (
                    "The audience filter resolves to zero contacts. "
                    "Widen the filter or pick a different saved group."
                ),
            }
        )

    if is_email:
        # --- Store Profile postal address (CAN-SPAM) ---------------
        org_settings = (
            await session.execute(select(OrgSettings).where(OrgSettings.org_id == campaign.org_id))
        ).scalar_one_or_none()
        if not tracking_footer.has_required_address(org_settings):
            blockers.append(
                {
                    "code": "missing_postal_address",
                    "message": (
                        "Your organisation has no physical address configured. "
                        "Add one in Settings → Store Profile before sending — "
                        "CAN-SPAM and DPDP both require it on every marketing "
                        "email."
                    ),
                }
            )

        # --- Mailbox + domain readiness ----------------------------
        # ``_check_email_sender_readiness`` raises for hard blockers and
        # returns warnings for soft degradations. Wrap the raise into a
        # structured blocker instead so the endpoint stays 200.
        try:
            email_warnings = await _check_email_sender_readiness(session, campaign=campaign)
            for note in email_warnings:
                warnings.append({"code": "email_sender_degraded", "message": note})
        except HTTPException as exc:  # already 400 with a friendly detail
            blockers.append(
                {
                    "code": "email_sender_block",
                    "message": str(exc.detail),
                }
            )

        # --- Audience eligibility (opt-out / no email / bounces) ----
        if audience_size:
            from src.app.core.campaigns.send_guard import evaluate_email_contact

            contacts_rows = (
                await session.execute(
                    select(
                        Contact.id,
                        Contact.email,
                        Contact.email_opt_out,
                        Contact.email_opt_in_status,
                    ).where(Contact.id.in_(contact_ids))
                )
            ).all()

            allowed_ids: list[uuid.UUID] = []
            for row in contacts_rows:
                _cid, email, opt_out, opt_status = row
                if not email:
                    excluded_no_email += 1
                    continue
                # Mirror dispatch's ``allow_implicit=True`` so the count
                # matches what dispatch would keep.

                class _StubContact:
                    email_opt_out = opt_out
                    email_opt_in_status = opt_status

                decision = evaluate_email_contact(_StubContact(), allow_implicit=True)
                if decision.verdict == "block":
                    excluded_opted_out += 1
                else:
                    allowed_ids.append(_cid)

            # Bounce suppression, same helper enqueue calls. Cheap: one
            # bulk `IN(...)` query against the hard-bounce set.
            _, excluded_bounced = await _suppress_bounced_contacts(
                session, campaign=campaign, contact_ids=allowed_ids
            )
            eligible = audience_size - excluded_no_email - excluded_opted_out - excluded_bounced

            if eligible == 0 and audience_size > 0:
                blockers.append(
                    {
                        "code": "no_eligible_contacts",
                        "message": (
                            f"None of the {audience_size} audience contacts "
                            "can receive this email — every recipient is "
                            "opted-out, missing an email address, or on the "
                            "bounce list. Fix the filter or opt-in state "
                            "before sending."
                        ),
                    }
                )

    # A/B minimum-audience guard mirrors the enqueue check so the
    # wizard warns the operator before Start.
    if campaign.is_ab_test and eligible < 50:
        blockers.append(
            {
                "code": "ab_audience_too_small",
                "message": (
                    f"A/B campaigns need at least 50 eligible recipients "
                    f"to keep the winner metric meaningful. This audience "
                    f"has {eligible}. Reduce the A/B toggle or widen "
                    "the filter."
                ),
            }
        )

    return {
        "campaign_id": campaign.id,
        "channel": campaign.channel.value,
        "audience_size": audience_size,
        "eligible_count": max(0, eligible),
        "excluded_opted_out": excluded_opted_out,
        "excluded_no_email": excluded_no_email,
        "excluded_bounced": excluded_bounced,
        "blockers": blockers,
        "warnings": warnings,
    }


async def _validate_template_channel_match(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    campaign_channel: ConversationChannel,
    template_ids: list[uuid.UUID],
) -> None:
    """tasks/template-library Step 11 — confirm every referenced
    template's channel matches the campaign's channel.

    Loads each id from the central library; raises 422 if any
    template's channel differs or the id doesn't resolve in this org.
    Skipped when no template ids are supplied (free-text campaign).
    """
    from src.app.core.templates import service as templates_service

    for tid in template_ids:
        row = await templates_service.find_template(session, org_id=org_id, template_id=tid)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"template {tid} not found in this org",
            )
        if row.channel != campaign_channel:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"template {tid} has channel '{row.channel.value}' "
                    f"but the campaign is on '{campaign_channel.value}'"
                ),
            )


async def create_campaign(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: CampaignCreate,
) -> Campaign:
    template_ids_to_check: list[uuid.UUID] = []
    if payload.template_id is not None:
        template_ids_to_check.append(payload.template_id)
    if payload.is_ab_test:
        if payload.variant_a_template_id is not None:
            template_ids_to_check.append(payload.variant_a_template_id)
        if payload.variant_b_template_id is not None:
            template_ids_to_check.append(payload.variant_b_template_id)
    if template_ids_to_check:
        await _validate_template_channel_match(
            session,
            org_id=org_id,
            campaign_channel=payload.channel,
            template_ids=template_ids_to_check,
        )
    # Campaigns v1 Step 03 — verify the referenced sender identity
    # exists + is usable. The schema layer already enforced that
    # exactly one of email_account_id / smtp_sender_id is set on
    # Email campaigns; here we do the cross-module read + status
    # gate that only the service layer can own.
    if payload.channel == ConversationChannel.email:
        if payload.email_account_id is not None:
            await _resolve_email_sender(
                session,
                org_id=org_id,
                account_id=payload.email_account_id,
            )
        elif payload.smtp_sender_id is not None:
            await _resolve_smtp_sender(
                session,
                org_id=org_id,
                sender_id=payload.smtp_sender_id,
            )
    campaign = Campaign(
        org_id=org_id,
        name=payload.name,
        channel=payload.channel,
        audience_filter=payload.audience_filter.model_dump(exclude_none=True, mode="json"),
        template=payload.template,
        template_id=payload.template_id,
        template_variables=(
            {k: v.model_dump() for k, v in payload.template_variables.items()}
            if payload.template_variables is not None
            else None
        ),
        schedule_at=payload.schedule_at,
        # Step 27b — pin the campaign to a specific WhatsApp phone
        # when the operator chose one on the create modal. NULL
        # preserves the legacy "use org default" behaviour.
        send_from_phone_id=payload.send_from_phone_id,
        # Campaigns v1 Step 03 — Email sender identity + subject + preheader.
        # Persisted verbatim for Email campaigns; NULL on non-Email rows
        # even if the payload happened to send them (the schema validator
        # already rejected any Email-specific value on a WA payload via
        # the required-when-Email check, and non-Email payloads simply
        # default these to None).
        email_account_id=payload.email_account_id,
        smtp_sender_id=payload.smtp_sender_id,
        sender_name=payload.sender_name,
        reply_to=str(payload.reply_to) if payload.reply_to is not None else None,
        subject=payload.subject,
        preheader=payload.preheader,
        # Campaigns v1 Step 04 — inline HTML body for Email campaigns
        # authored in the create modal (not linked to a template).
        # Sanitised before persist; schema validator already rejected
        # non-Email payloads that supplied it.
        body_html=(
            sanitize_email_html(payload.body_html) if payload.body_html is not None else None
        ),
        # Step 29 — A/B test config. Server defaults take over for
        # non-A/B campaigns (is_ab_test=false, split_ratio=50, etc.).
        is_ab_test=bool(payload.is_ab_test),
        variant_a_template_id=payload.variant_a_template_id if payload.is_ab_test else None,
        variant_b_template_id=payload.variant_b_template_id if payload.is_ab_test else None,
        split_ratio=int(payload.split_ratio),
        winner_metric=payload.winner_metric if payload.is_ab_test else None,
        winner_holdback_hours=int(payload.winner_holdback_hours),
        status=CampaignStatus.draft,
        created_by_id=user_id,
    )
    campaigns_da.add_campaign(session, campaign)
    await session.commit()
    await session.refresh(campaign)
    await log_entity_change(
        action="campaigns.created",
        entity_type="campaign",
        entity_id=campaign.id,
        after=_snapshot(campaign),
    )

    # Auto-arm scheduled campaigns: when the operator sets a future
    # `schedule_at` at create time, skip the manual Start click and run
    # the enqueue pre-flight (readiness checks, audience resolution,
    # chunk pre-queue) inline. The campaign lands in `scheduled` state
    # with queued rows so the `dispatch_scheduled_campaigns` beat picks
    # it up at `schedule_at` without further input. If pre-flight
    # raises (missing store address, template channel mismatch, etc.),
    # roll back the just-created row so the operator can fix + retry
    # without a phantom draft in the list.
    if campaign.schedule_at is not None and campaign.schedule_at > datetime.now(UTC):
        try:
            await enqueue(session, campaign_id=campaign.id)
            await session.refresh(campaign)
        except HTTPException:
            await campaigns_da.delete_campaign_row(session, campaign)
            await session.commit()
            raise
    return campaign


async def update_campaign(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    payload: CampaignUpdate,
) -> Campaign:
    campaign = await get_campaign(session, campaign_id)
    if campaign.status != CampaignStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot edit a {campaign.status.value} campaign",
        )
    before = _snapshot(campaign)
    changed = False
    if payload.name is not None:
        campaign.name = payload.name
        changed = True
    if payload.audience_filter is not None:
        campaign.audience_filter = payload.audience_filter.model_dump(
            exclude_none=True, mode="json"
        )
        changed = True
    if payload.template is not None:
        campaign.template = payload.template
        # Switching to free-text body clears any template binding so
        # the row never has both — dispatch's branch (Step 3.5.6) is
        # unambiguous.
        campaign.template_id = None
        campaign.template_variables = None
        changed = True
    if payload.template_id is not None:
        campaign.template_id = payload.template_id
        campaign.template = None
        campaign.template_variables = (
            {k: v.model_dump() for k, v in payload.template_variables.items()}
            if payload.template_variables is not None
            else {}
        )
        changed = True
    if payload.schedule_at is not None:
        campaign.schedule_at = payload.schedule_at
        changed = True
    # Campaigns v1 Step 03 — Email sender identity + subject + preheader
    # can be edited on a Draft Email campaign. Channel itself is
    # immutable post-create, so we don't have to re-run the
    # required-when-Email check — any missing required field just stays
    # at whatever the create-time payload set. Swapping the mailbox
    # re-triggers the connection check.
    if (
        payload.email_account_id is not None
        and payload.email_account_id != campaign.email_account_id
    ):
        await _resolve_email_sender(
            session,
            org_id=campaign.org_id,
            account_id=payload.email_account_id,
        )
        campaign.email_account_id = payload.email_account_id
        # Flipping to an OAuth mailbox clears any prior SMTP sender so
        # the row keeps satisfying the exactly-one CHECK constraint.
        campaign.smtp_sender_id = None
        changed = True
    if payload.smtp_sender_id is not None and payload.smtp_sender_id != campaign.smtp_sender_id:
        await _resolve_smtp_sender(
            session,
            org_id=campaign.org_id,
            sender_id=payload.smtp_sender_id,
        )
        campaign.smtp_sender_id = payload.smtp_sender_id
        # Flipping to an SMTP sender clears any prior OAuth mailbox so
        # the row keeps satisfying the exactly-one CHECK constraint.
        campaign.email_account_id = None
        changed = True
    if payload.sender_name is not None:
        campaign.sender_name = payload.sender_name
        changed = True
    if payload.reply_to is not None:
        campaign.reply_to = str(payload.reply_to)
        changed = True
    if payload.subject is not None:
        campaign.subject = payload.subject
        changed = True
    if payload.preheader is not None:
        campaign.preheader = payload.preheader
        changed = True
    # Campaigns v1 Step 04 — inline HTML body edits. Only meaningful
    # for Email campaigns; the schema validator on CampaignUpdate
    # accepts it for any channel but the create-time validator has
    # already gated the source-of-truth invariant on the row.
    if payload.body_html is not None:
        new_html = sanitize_email_html(payload.body_html)
        if new_html != campaign.body_html:
            campaign.body_html = new_html
            changed = True
    if changed:
        await session.commit()
        await session.refresh(campaign)
        await log_entity_change(
            action="campaigns.updated",
            entity_type="campaign",
            entity_id=campaign.id,
            before=before,
            after=_snapshot(campaign),
        )
    return campaign


async def delete_campaign(session: AsyncSession, *, campaign_id: uuid.UUID) -> None:
    campaign = await get_campaign(session, campaign_id)
    # Draft / Failed remain hard-deletable at any time. Sent / Scheduled /
    # Running normally aren't (their message receipts back the reporting
    # UI), but once an operator has archived a campaign they've
    # consciously said "I don't need this anymore" — permit hard-delete
    # from the Archived slice regardless of underlying status. The FK
    # cascades the drop into ``tbl_campaign_messages``.
    if campaign.archived_at is None and campaign.status not in (
        CampaignStatus.draft,
        CampaignStatus.failed,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot delete a {campaign.status.value} campaign",
        )
    before = _snapshot(campaign)
    await campaigns_da.delete_campaign_row(session, campaign)
    await session.commit()
    await log_entity_change(
        action="campaigns.deleted",
        entity_type="campaign",
        entity_id=campaign_id,
        before=before,
    )


# Statuses that can be soft-archived. Scheduled and Running are
# deliberately excluded — those campaigns still have in-flight side
# effects (queued rows, worker dispatches) and should be cancelled
# rather than hidden. Extending this tuple is a policy decision.
_ARCHIVABLE_STATUSES = (
    CampaignStatus.draft,
    CampaignStatus.done,
    CampaignStatus.failed,
)


async def archive_campaign(session: AsyncSession, *, campaign_id: uuid.UUID) -> Campaign:
    """Soft-archive a campaign so it disappears from the default list
    and the sender-in-use pre-check. Metrics rows on
    ``tbl_campaign_messages`` are preserved. Idempotent — archiving an
    already-archived campaign is a no-op that still returns the row.
    """
    campaign = await get_campaign(session, campaign_id)
    if campaign.status not in _ARCHIVABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"cannot archive a {campaign.status.value} campaign — cancel it first"),
        )
    if campaign.archived_at is not None:
        return campaign
    before = _snapshot(campaign)
    await campaigns_da.archive_campaign_row(session, campaign, now=datetime.now(UTC))
    await session.commit()
    await session.refresh(campaign)
    await log_entity_change(
        action="campaigns.archived",
        entity_type="campaign",
        entity_id=campaign_id,
        before=before,
        after=_snapshot(campaign),
    )
    return campaign


async def unarchive_campaign(session: AsyncSession, *, campaign_id: uuid.UUID) -> Campaign:
    """Restore a soft-archived campaign to the default list.
    Idempotent — unarchiving an already-active row is a no-op."""
    campaign = await get_campaign(session, campaign_id)
    if campaign.archived_at is None:
        return campaign
    before = _snapshot(campaign)
    await campaigns_da.unarchive_campaign_row(session, campaign)
    await session.commit()
    await session.refresh(campaign)
    await log_entity_change(
        action="campaigns.unarchived",
        entity_type="campaign",
        entity_id=campaign_id,
        before=before,
        after=_snapshot(campaign),
    )
    return campaign


# --- audience -----------------------------------------------------------


async def resolve_audience(
    session: AsyncSession, *, audience_filter: dict[str, Any]
) -> list[uuid.UUID]:
    """Translate the campaign's `audience_filter` JSONB into a list of
    contact ids. Four modes per `AudienceFilter`:

      - Empty filter → every contact in the org (RLS handles isolation).
      - `group_id` set → delegate to `contact_groups.resolve_group_contacts`
        which honours static-vs-dynamic group semantics.
      - `q/source/tag` set → run the predicate directly.
      - `contact_ids` set → send to exactly those ids (scoped through
        the tenant filter so cross-org ids drop out).

    A campaign that references a deleted group resolves to an empty
    list — the dispatch path then marks all queued messages failed
    with a clear "audience empty" error rather than silently sending
    zero messages."""
    af = AudienceFilter.model_validate(audience_filter or {})

    if af.contact_ids:
        return await campaigns_da.list_contact_ids_in_scope(session, ids=af.contact_ids)

    if af.group_id is not None:
        # Saved-group mode. Use a delayed import to avoid the
        # `contacts.groups → campaigns` direction (groups doesn't
        # know about campaigns; campaigns reaches in).
        from src.app.core.contacts.groups.service import (
            get_group,
            resolve_group_contacts,
        )

        try:
            await get_group(session, af.group_id)
        except HTTPException:
            # Group deleted (Step 3.5.7 hard-delete) — empty audience.
            return []
        return await resolve_group_contacts(session, group_id=af.group_id)

    # Filter mode (q / source / tag / lead_*) — falls through to ""
    # empty filter = "everyone" by intentional design.
    return await campaigns_da.list_contact_ids_for_audience(
        session,
        q=af.q,
        source=af.source,
        tag=af.tag,
        lead_statuses=af.lead_status,
        lead_stages=af.lead_stage,
        lead_sources=af.lead_source,
        lead_form_ids=af.lead_form_id,
    )


# --- start + dispatch ----------------------------------------------------


async def enqueue(session: AsyncSession, *, campaign_id: uuid.UUID) -> dict[str, Any]:
    """Resolve audience → split into chunks → dispatch Celery tasks.

    Returns a small summary the router echoes back to the operator
    (audience_size + chunks_enqueued + scheduled_at).
    """
    await get_campaign(session, campaign_id)
    # Row lock held until the status flip commits — a concurrent
    # second Start waits, then sees `running` and gets the 409.
    campaign = await campaigns_da.get_campaign_for_update(session, campaign_id)
    assert campaign is not None  # noqa: S101 — existence checked above
    restarting = campaign.status == CampaignStatus.failed
    if campaign.status not in (CampaignStatus.draft, CampaignStatus.failed):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"campaign already {campaign.status.value}",
        )
    # Adapter must exist before we accept the start request. WhatsApp
    # uses the per-org resolver (Step 3.5.3) — checking the generic
    # registry would always fail for it. Mirror the branch used in
    # `dispatch_chunk` so a connected org passes pre-flight and a
    # disconnected one is rejected with a clear message.
    try:
        if campaign.channel == ConversationChannel.whatsapp:
            await resolve_whatsapp_adapter(
                session,
                phone_id=campaign.send_from_phone_id,
            )
        else:
            resolve_channel(campaign.channel)
    except (ChannelNotRegistered, WhatsAppNotConnected) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # Campaigns v1 Step 07 — Email sender-readiness pre-flight. The
    # mailbox lookup already happened at create time (Step 03's
    # ``_resolve_email_sender``); here we cross-check the mailbox's
    # domain against the sender-setup registry so an unverified
    # domain either warns (default) or hard-blocks (per-org flag).
    # Campaigns v1 Step 07c — additionally block on missing postal
    # address (CAN-SPAM) so the operator sees one clear error before
    # every message fails inside ``send_email``.
    if campaign.channel == ConversationChannel.email:
        from sqlalchemy import select as _select

        from src.app.core.email.tracking import footer as tracking_footer
        from src.app.core.settings.models import OrgSettings

        # Raise-only pre-flight — the returned warnings list stays
        # unused here (dispatch surfaces them per-message today; the
        # readiness endpoint is the structured surface).
        await _check_email_sender_readiness(session, campaign=campaign)
        org_settings = (
            await session.execute(_select(OrgSettings).where(OrgSettings.org_id == campaign.org_id))
        ).scalar_one_or_none()
        if not tracking_footer.has_required_address(org_settings):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Your organisation has no physical address configured. "
                    "Add one in Settings → Store Profile before sending — "
                    "CAN-SPAM and DPDP both require it on every marketing "
                    "email."
                ),
            )

    contact_ids = await resolve_audience(session, audience_filter=campaign.audience_filter)

    # Campaigns v1 Step 07 — Email bounce suppression. Contacts on the
    # org's hard-bounce / spam-complaint list are silently excluded
    # from the audience; the delta lands on ``excluded_bounced_count``
    # so the campaign detail page can render "N excluded" honestly.
    if campaign.channel == ConversationChannel.email and contact_ids:
        contact_ids, bounced_excluded = await _suppress_bounced_contacts(
            session, campaign=campaign, contact_ids=contact_ids
        )
        if bounced_excluded:
            campaign.excluded_bounced_count = int(bounced_excluded)

    # whatsapp-platform-upgrade Step 29 — minimum-audience guard.
    # A/B requires ≥ 50 recipients to keep the winner metric out
    # of statistical noise. The spec calls this out explicitly:
    # smaller audiences produce flaky winners.
    if campaign.is_ab_test and len(contact_ids) < 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"A/B campaigns need at least 50 recipients to keep "
                f"the winner metric statistically meaningful. This "
                f"audience has {len(contact_ids)}. Reduce the A/B "
                f"toggle or widen the audience filter."
            ),
        )

    if not contact_ids:
        campaign.status = CampaignStatus.done
        await session.commit()
        await session.refresh(campaign)
        await audit.log(
            "campaigns.empty_audience",
            entity_type="campaign",
            entity_id=campaign.id,
        )
        return {
            "campaign_id": campaign.id,
            "status": campaign.status,
            "audience_size": 0,
            "chunks_enqueued": 0,
            "scheduled_at": campaign.schedule_at,
        }

    # Flip to running (or scheduled if schedule_at is in the future).
    now = datetime.now(UTC)
    is_scheduled = campaign.schedule_at is not None and campaign.schedule_at > now
    campaign.status = CampaignStatus.scheduled if is_scheduled else CampaignStatus.running
    await session.commit()

    chunks = [contact_ids[i : i + CHUNK_SIZE] for i in range(0, len(contact_ids), CHUNK_SIZE)]

    # Restarting a failed campaign re-sends the rows that failed.
    if restarting:
        await campaigns_da.requeue_failed_messages(session, campaign_id=campaign.id)
        await session.commit()

    # Pre-queue placeholder rows so stats immediately reflect "queued: N".
    for chunk in chunks:
        await _queue_chunk_rows(session, campaign_id=campaign.id, contact_ids=chunk)

    # Step 3.5.14 — Celery-aware dispatch.
    #
    # CELERY_ENABLED=true (prod): each chunk goes to Celery via
    # `.delay(...)`; the API request returns immediately while workers
    # burn through chunks at the per-org rate (Step 3.5.15).
    # CELERY_ENABLED=false (dev): tasks run eager-inline through the
    # shim so smoke tests don't need a worker.
    #
    # Scheduled-for-future campaigns stay in `status='scheduled'` with
    # their queued rows pre-inserted; the beat task
    # `dispatch_scheduled_campaigns` picks them up every 60s.
    if not is_scheduled:
        await _fan_out_chunks(
            session,
            campaign=campaign,
            contact_ids=contact_ids,
            schedule_ab_decider=campaign.is_ab_test,
        )

    await audit.log(
        "campaigns.started",
        entity_type="campaign",
        entity_id=campaign.id,
        after={
            "audience_size": len(contact_ids),
            "chunks": len(chunks),
            "scheduled": is_scheduled,
        },
    )
    await session.refresh(campaign)
    return {
        "campaign_id": campaign.id,
        "status": campaign.status,
        "audience_size": len(contact_ids),
        "chunks_enqueued": len(chunks),
        "scheduled_at": campaign.schedule_at,
    }


async def _fan_out_chunks(
    session: AsyncSession,
    *,
    campaign: Campaign,
    contact_ids: list[uuid.UUID],
    schedule_ab_decider: bool,
) -> None:
    """Hand the contacts to the sender in `CHUNK_SIZE` batches.

    CELERY_ENABLED=true (prod): each chunk goes to a worker via
    `.delay(...)` so the caller returns immediately. Otherwise the
    chunks run inline (dev / eager smoke tests).

    ``schedule_ab_decider`` arms the A/B winner decider
    `winner_holdback_hours` after dispatch — only on the first start
    of an A/B campaign (immediate or scheduled), never on a stall
    re-dispatch. The task is idempotent + checks `winning_variant is
    NULL`, so a duplicate arm can't double-flip."""
    from config import CELERY_ENABLED as _CELERY_ENABLED
    from src.app.core.campaigns.tasks import HAS_CELERY, send_campaign_chunk

    chunks = [contact_ids[i : i + CHUNK_SIZE] for i in range(0, len(contact_ids), CHUNK_SIZE)]
    if not (HAS_CELERY and _CELERY_ENABLED):
        for chunk in chunks:
            await dispatch_chunk(session, campaign_id=campaign.id, contact_ids=chunk)
        return
    for chunk in chunks:
        send_campaign_chunk.delay(str(campaign.id), [str(c) for c in chunk])
    if schedule_ab_decider:
        try:
            from src.app.core.campaigns.tasks import run_ab_decision

            run_ab_decision.apply_async(
                args=[str(campaign.id)],
                countdown=int(campaign.winner_holdback_hours) * 3600,
            )
        except Exception:  # noqa: BLE001
            logger.exception("could not schedule A/B decider for campaign %s", campaign.id)


# Scheduled sweep + stall recovery (driven by the
# `dispatch_scheduled_campaigns` beat task every 60s).
_SWEEP_BATCH_LIMIT = 100
# A running campaign with queued rows and no send for this long lost its
# chunk task (worker restart, broker outage, hard time limit). Well above
# the 300s task hard limit so an in-flight chunk is never re-dispatched.
_STALL_AFTER = timedelta(minutes=15)


async def list_due_scheduled_campaign_refs(
    session: AsyncSession,
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Cross-org `(campaign_id, org_id)` of scheduled campaigns now due."""
    return await campaigns_da.list_due_scheduled_campaigns(
        session, now=datetime.now(UTC), limit=_SWEEP_BATCH_LIMIT
    )


async def list_stalled_campaign_refs(
    session: AsyncSession,
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Cross-org `(campaign_id, org_id)` of running campaigns whose
    chunk tasks were lost."""
    return await campaigns_da.list_stalled_running_campaigns(
        session, cutoff=datetime.now(UTC) - _STALL_AFTER, limit=_SWEEP_BATCH_LIMIT
    )


async def start_scheduled_campaign(session: AsyncSession, *, campaign_id: uuid.UUID) -> bool:
    """Claim a due scheduled campaign (`scheduled` → `running`) and send
    its queued rows. Returns False when another sweep claimed it first."""
    claimed = await campaigns_da.claim_scheduled_campaign(
        session, campaign_id=campaign_id, now=datetime.now(UTC)
    )
    await session.commit()
    if not claimed:
        return False
    campaign = await get_campaign(session, campaign_id)
    await session.refresh(campaign)
    queued = await campaigns_da.list_queued_contact_ids(session, campaign_id=campaign_id)
    if not queued:
        await _settle_campaign_status(session, campaign_id=campaign_id)
        return True
    await _fan_out_chunks(
        session,
        campaign=campaign,
        contact_ids=queued,
        schedule_ab_decider=campaign.is_ab_test,
    )
    return True


async def resume_stalled_campaign(session: AsyncSession, *, campaign_id: uuid.UUID) -> int:
    """Re-dispatch a stalled running campaign's queued rows. Returns the
    number of contacts handed back to the sender."""
    campaign = await get_campaign(session, campaign_id)
    queued = await campaigns_da.list_queued_contact_ids(session, campaign_id=campaign_id)
    if not queued:
        await _settle_campaign_status(session, campaign_id=campaign_id)
        return 0
    logger.warning(
        "re-dispatching stalled campaign",
        extra={"campaign_id": str(campaign_id), "queued": len(queued)},
    )
    await _fan_out_chunks(session, campaign=campaign, contact_ids=queued, schedule_ab_decider=False)
    return len(queued)


async def _queue_chunk_rows(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    contact_ids: list[uuid.UUID],
) -> None:
    """Insert one `CampaignMessage` row per contact at status='queued'.

    `ON CONFLICT DO NOTHING` on the (campaign_id, contact_id) unique
    index makes this idempotent — a retried `start` won't duplicate.
    """
    campaign = await get_campaign(session, campaign_id)
    rows = [
        {
            "org_id": campaign.org_id,
            "campaign_id": campaign_id,
            "contact_id": cid,
            "status": CampaignMessageStatus.queued,
        }
        for cid in contact_ids
    ]
    if not rows:
        return
    await campaigns_da.bulk_upsert_queued_campaign_messages(session, rows=rows)
    await session.commit()


# --- the actual sender (called from the Celery task) ---------------------


class _ChunkRestart(Exception):
    """One contact's send left the session unusable; the chunk resumes
    on the rows that are still queued."""


async def dispatch_chunk(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    contact_ids: list[uuid.UUID],
) -> None:
    """Send to the chunk's still-`queued` contacts, then settle the
    campaign status once no queued rows remain.

    Finished rows are skipped, so a Celery retry, a double start or a
    stall-recovery re-dispatch never re-sends. An unexpected
    per-contact error fails that row and restarts the chunk; an
    unexpected chunk-level error fails the remaining rows so the
    campaign can't sit in `running` forever."""
    while True:
        remaining = await campaigns_da.list_queued_contact_ids(
            session, campaign_id=campaign_id, contact_ids=contact_ids
        )
        if not remaining:
            break
        try:
            await _dispatch_chunk_rows(session, campaign_id=campaign_id, contact_ids=remaining)
            break
        except _ChunkRestart:
            continue
        except (ConnectionError, TimeoutError):
            # Transient infra error — Celery retries the chunk; the rows
            # stay queued for the retry / stall recovery.
            raise
        except Exception as exc:
            logger.exception("campaign chunk aborted", extra={"campaign_id": str(campaign_id)})
            await session.rollback()
            await campaigns_da.fail_queued_messages(
                session,
                campaign_id=campaign_id,
                contact_ids=remaining,
                error=f"send aborted: {exc}"[:512],
            )
            await session.commit()
            break
    await _settle_campaign_status(session, campaign_id=campaign_id)


async def _settle_campaign_status(session: AsyncSession, *, campaign_id: uuid.UUID) -> None:
    """Close out a campaign once nothing is queued: `done` when at least
    one message went out, `failed` when every message failed."""
    campaign = await get_campaign(session, campaign_id)
    await session.refresh(campaign)
    if campaign.status not in (CampaignStatus.running, CampaignStatus.failed):
        return
    counts = dict(await campaigns_da.stats_by_status(session, campaign_id=campaign_id))
    if counts.get(CampaignMessageStatus.queued, 0):
        return
    any_delivered = any(n for st, n in counts.items() if st != CampaignMessageStatus.failed)
    settled = CampaignStatus.done if any_delivered or not counts else CampaignStatus.failed
    if campaign.status != settled:
        campaign.status = settled
        await session.commit()


async def _dispatch_chunk_rows(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    contact_ids: list[uuid.UUID],
) -> None:
    """Send the template to each contact via the adapter; persist
    `CampaignMessage` status + `channel_message_id`."""
    campaign = await get_campaign(session, campaign_id)
    # WhatsApp uses the per-org resolver (Step 3.5.3) which loads the
    # campaign org's encrypted token from the integrations table. A
    # disconnected org raises `WhatsAppNotConnected` — caught here
    # alongside `ChannelNotRegistered` so the same failure surface
    # works for both "channel never wired" and "org never connected".
    try:
        if campaign.channel == ConversationChannel.whatsapp:
            # Step 27a — pin the adapter to the campaign's chosen
            # send-from phone (NULL falls back to the org default).
            adapter = await resolve_whatsapp_adapter(
                session,
                phone_id=campaign.send_from_phone_id,
            )
        else:
            adapter = resolve_channel(campaign.channel)
    except (ChannelNotRegistered, WhatsAppNotConnected) as exc:
        # Mark every queued row as failed so the UI surfaces the
        # configuration gap.
        for cid in contact_ids:
            await _mark_message(
                session,
                campaign_id=campaign_id,
                contact_id=cid,
                new_status=CampaignMessageStatus.failed,
                error=str(exc),
            )
        return

    # Template campaigns (Step 3.5.6): load the WhatsAppTemplate
    # extension row once per chunk. Post-Step-11 the FK on the
    # campaign points at ``tbl_message_templates`` (central library);
    # the WA extension carries the Meta-specific fields we need for
    # ``adapter.send_template`` (name / language / header). Lookup
    # via the Step-9 reciprocal link ``message_template_id``.
    #
    # Only WhatsApp campaigns need this extension row — email
    # campaigns resolve their template body via
    # ``templates_service.find_template`` in the email-specific block
    # below (line ~1118). Firing the WA-extension check for a non-WA
    # channel misreports every recipient as "Template no longer
    # exists locally — re-sync from Settings → Integrations →
    # WhatsApp." even when the email template is present.
    template_row: WhatsAppTemplate | None = None
    template_a_row: WhatsAppTemplate | None = None
    template_b_row: WhatsAppTemplate | None = None
    if campaign.channel == ConversationChannel.whatsapp and campaign.is_ab_test:
        ids = [
            tid
            for tid in (
                campaign.variant_a_template_id,
                campaign.variant_b_template_id,
            )
            if tid is not None
        ]
        by_central = await campaigns_da.get_wa_extensions_for_template_ids(session, ids)
        template_a_row = by_central.get(campaign.variant_a_template_id)
        template_b_row = by_central.get(campaign.variant_b_template_id)
        if template_a_row is None or template_b_row is None:
            for cid in contact_ids:
                await _mark_message(
                    session,
                    campaign_id=campaign_id,
                    contact_id=cid,
                    new_status=CampaignMessageStatus.failed,
                    error=(
                        "A/B variant template no longer exists locally "
                        "— re-sync from Settings → Integrations → WhatsApp."
                    ),
                )
            return
        # When a winner has already been chosen, route every recipient
        # in this chunk to the winning template (legacy single-template
        # branch). Subsequent contacts beyond the original split land
        # here.
        if campaign.winning_variant == "A":
            template_row = template_a_row
        elif campaign.winning_variant == "B":
            template_row = template_b_row
    elif campaign.channel == ConversationChannel.whatsapp and campaign.template_id is not None:
        # Step 11 — lookup the WA extension via the central row's id
        # (the campaign's `template_id` now points at the central
        # library, not the WA extension).
        template_row = await campaigns_da.get_wa_extension_for_campaign_template(
            session, campaign.template_id
        )
        if template_row is None:
            for cid in contact_ids:
                await _mark_message(
                    session,
                    campaign_id=campaign_id,
                    contact_id=cid,
                    new_status=CampaignMessageStatus.failed,
                    error=(
                        "Template no longer exists locally — re-sync "
                        "from Settings → Integrations → WhatsApp."
                    ),
                )
            return

    # Step 3.5.15 — per-org rate cap. Fetch once per chunk; the same
    # value applies to every contact in this dispatch. Non-WA channels
    # bypass this (no token-bucket coupling).
    wa_rate_per_sec = 50
    if campaign.channel == ConversationChannel.whatsapp:
        from src.app.core.integrations.whatsapp.connect import get_active_config

        # Step 27a — rate limit follows the campaign's chosen phone
        # (NULL → org default). Each Meta phone has its own throughput
        # tier; mismatching them under-utilises the higher-tier number.
        bundle = await get_active_config(session, phone_id=campaign.send_from_phone_id)
        if bundle is not None:
            _, _wa_config = bundle
            wa_rate_per_sec = max(1, int(_wa_config.rate_limit_per_sec or 50))

    # Once-per-chunk org load. Powers the ``{{org.name}}`` resolution
    # in :func:`_resolve_named_wa_variables` — every contact in the
    # chunk shares the same org so we skip a re-fetch per row.
    org: Organization | None = None
    # Once-per-chunk named-body fallback. The WA cache row's ``body``
    # column is Meta's positional copy — we lose named variable info
    # after the first Meta sync. Fetch the central-library row's
    # ``body_text`` (still named) so ``_resolve_named_wa_variables``
    # can recover the ordered param names when ``body_components``
    # is missing/empty on older synced rows.
    named_body_from_central: str | None = None
    if campaign.channel == ConversationChannel.whatsapp and template_row is not None:
        org = (
            await session.execute(select(Organization).where(Organization.id == campaign.org_id))
        ).scalar_one_or_none()
        central_id = getattr(template_row, "message_template_id", None)
        if central_id is not None:
            from src.app.core.templates.models import MessageTemplate

            central_row = (
                await session.execute(
                    select(MessageTemplate.body_text).where(MessageTemplate.id == central_id)
                )
            ).scalar_one_or_none()
            if isinstance(central_row, str) and central_row.strip():
                named_body_from_central = central_row

    # Step 22 — DPDP opt-in pre-flight check. Marketing campaigns on
    # opted-out contacts must never ship; the dashboard's failure
    # classifier already maps "opted out" into its own bucket.
    from src.app.core.campaigns.send_guard import (
        block_reason,
        evaluate_contact,
    )

    # Campaigns v1 Step 05 — Email dispatch preload. The mailbox
    # owns the `user_id` used as `sender_user_id` in send_email; the
    # template's HTML + text land the body when the campaign references
    # one. Both loads are once-per-chunk (not once-per-contact).
    email_account: EmailAccount | None = None
    email_smtp_sender: EmailSmtpSender | None = None
    email_template_body_html: str | None = None
    email_template_body_text: str | None = None
    email_template_subject: str | None = None
    if campaign.channel == ConversationChannel.email:
        # Migration 0213 — exactly one of email_account_id / smtp_sender_id
        # is set on Email rows (schema + DB CHECK enforce). Resolve the
        # matching sender once for the chunk instead of per-recipient.
        if campaign.email_account_id is None and campaign.smtp_sender_id is None:
            for cid in contact_ids:
                await _mark_message(
                    session,
                    campaign_id=campaign_id,
                    contact_id=cid,
                    new_status=CampaignMessageStatus.failed,
                    error="email campaign has no sender identity",
                )
            return
        if campaign.email_account_id is not None:
            email_account = await email_da.get_account_by_id(
                session, account_id=campaign.email_account_id
            )
            if email_account is None or email_account.org_id != campaign.org_id:
                for cid in contact_ids:
                    await _mark_message(
                        session,
                        campaign_id=campaign_id,
                        contact_id=cid,
                        new_status=CampaignMessageStatus.failed,
                        error="sender mailbox not found or belongs to another org",
                    )
                return
            if email_account.sync_state != EmailAccountSyncState.live:
                for cid in contact_ids:
                    await _mark_message(
                        session,
                        campaign_id=campaign_id,
                        contact_id=cid,
                        new_status=CampaignMessageStatus.failed,
                        error="sender mailbox is not connected — reconnect it",
                    )
                return
        else:
            from src.app.core.email_senders import data_access as smtp_da

            email_smtp_sender = await smtp_da.get_by_id(
                session,
                org_id=campaign.org_id,
                sender_id=campaign.smtp_sender_id,
            )
            if email_smtp_sender is None:
                for cid in contact_ids:
                    await _mark_message(
                        session,
                        campaign_id=campaign_id,
                        contact_id=cid,
                        new_status=CampaignMessageStatus.failed,
                        error="SMTP sender not found or belongs to another org",
                    )
                return
            if email_smtp_sender.verified_at is None:
                for cid in contact_ids:
                    await _mark_message(
                        session,
                        campaign_id=campaign_id,
                        contact_id=cid,
                        new_status=CampaignMessageStatus.failed,
                        error=(
                            "SMTP sender is not verified — enter the 6-digit code "
                            "in Integrations → Email Sender"
                        ),
                    )
                return
        if campaign.template_id is not None:
            from src.app.core.templates import service as templates_service

            tpl = await templates_service.find_template(
                session, org_id=campaign.org_id, template_id=campaign.template_id
            )
            if tpl is None:
                for cid in contact_ids:
                    await _mark_message(
                        session,
                        campaign_id=campaign_id,
                        contact_id=cid,
                        new_status=CampaignMessageStatus.failed,
                        error="email template no longer exists in this org",
                    )
                return
            email_template_body_html = tpl.body_html
            email_template_body_text = tpl.body_text
            email_template_subject = tpl.subject or campaign.subject

    for cid in contact_ids:
        # Another dispatch (Celery retry, duplicate start, stall
        # recovery) may have finished this row since the chunk began.
        pending_row = await campaigns_da.get_campaign_message_for_contact(
            session, campaign_id=campaign_id, contact_id=cid
        )
        if pending_row is None or pending_row.status != CampaignMessageStatus.queued:
            continue
        try:
            contact = await contacts_service.get_contact(session, cid)
            if contact is None:
                await _mark_message(
                    session,
                    campaign_id=campaign_id,
                    contact_id=cid,
                    new_status=CampaignMessageStatus.failed,
                    error="contact not found",
                )
                continue
            # Channel-scoped external-id check. Non-Email channels write to
            # ``contact.phone``; Email requires an email address on file.
            if campaign.channel == ConversationChannel.email:
                if not contact.email:
                    await _mark_message(
                        session,
                        campaign_id=campaign_id,
                        contact_id=cid,
                        new_status=CampaignMessageStatus.failed,
                        error="contact has no email for this channel",
                    )
                    continue
            elif not contact.phone:
                await _mark_message(
                    session,
                    campaign_id=campaign_id,
                    contact_id=cid,
                    new_status=CampaignMessageStatus.failed,
                    error="contact has no phone for this channel",
                )
                continue

            # whatsapp-platform-upgrade Step 29 — per-recipient variant
            # assignment. Only applies during the A/B hold-out window
            # (before a winner is decided). Once the winner is set, the
            # earlier branch already pinned ``template_row`` to the
            # winning template + the variant tag stays NULL on the row.
            assigned_variant: str | None = None
            if (
                campaign.is_ab_test
                and campaign.winning_variant is None
                and template_a_row is not None
                and template_b_row is not None
            ):
                assigned_variant = _assign_ab_variant(
                    campaign_id=campaign.id,
                    contact_id=cid,
                    split_ratio=int(campaign.split_ratio),
                )
                template_row = template_a_row if assigned_variant == "A" else template_b_row

            # Channel-specific opt-in check. Other channels (SMS / email)
            # have their own opt-out columns; this guard only applies to
            # WhatsApp until those channels grow first-class opt-in cols.
            if campaign.channel == ConversationChannel.whatsapp:
                template_category = (
                    template_row.category.lower()
                    if template_row is not None and getattr(template_row, "category", None)
                    else None
                )
                decision = evaluate_contact(
                    contact,
                    template_category=template_category,
                    allow_implicit=True,
                )
                if decision.should_block:
                    await _mark_message(
                        session,
                        campaign_id=campaign_id,
                        contact_id=cid,
                        new_status=CampaignMessageStatus.failed,
                        error=block_reason(decision),
                    )
                    continue

                # Step 23 — block-list pre-flight. Same shape as the
                # opt-in guard above: mark failed + continue. The
                # Step-21 failure classifier maps the error string to
                # the `opted_out` bucket (closest match for "we won't
                # send"). Keep the message stable so the dashboard
                # numbers stay reconcilable across deploys.
                from src.app.core.integrations.whatsapp.block_list import (
                    is_blocked,
                )

                block_hit = await is_blocked(session, org_id=campaign.org_id, phone=contact.phone)
                if block_hit is not None:
                    await _mark_message(
                        session,
                        campaign_id=campaign_id,
                        contact_id=cid,
                        new_status=CampaignMessageStatus.failed,
                        error=(
                            f"send blocked: number is on the block list (reason: {block_hit.reason})"
                        ),
                    )
                    continue

            # Campaigns v1 Step 05 — Email dispatch path. Bypasses the WA
            # rate-limit + conversation-find flow entirely: send_email owns
            # its own account resolution, MIME composition, threading, and
            # inbox-message persistence.
            if campaign.channel == ConversationChannel.email:
                # Migration 0213 — exactly one of the two pre-loaded senders
                # is non-None here (guarded above). Retain the assertion so
                # a future refactor that adds a new sender kind trips fast.
                assert email_account is not None or email_smtp_sender is not None  # noqa: S101
                from fastapi import HTTPException as _HTTPExc

                from src.app.core.campaigns.send_guard import (
                    block_reason as _block_reason,
                )
                from src.app.core.campaigns.send_guard import (
                    evaluate_email_contact,
                )
                from src.app.core.conversations.adapters.email import send_email

                # Campaigns v1 Step 06 — Email opt-in guard, mirroring the
                # WA-side check. ``allow_implicit=True`` matches the WA
                # behaviour (the modal collected the operator's
                # confirmation flag; we default the same way here until a
                # dedicated Email consent toggle ships). Opted-out contacts
                # are always blocked regardless.
                email_decision = evaluate_email_contact(contact, allow_implicit=True)
                if email_decision.should_block:
                    await _mark_message(
                        session,
                        campaign_id=campaign_id,
                        contact_id=cid,
                        new_status=CampaignMessageStatus.failed,
                        error=_block_reason(email_decision),
                    )
                    continue

                # Resolve the subject + both body halves, substituting merge
                # tags per contact. Template-backed campaigns use the
                # template's body; inline-compose campaigns use the
                # campaign's body_html (Step 04 lands the field).
                eff_subject = email_template_subject if campaign.template_id else campaign.subject
                if campaign.template_id is not None:
                    eff_html = email_template_body_html
                    eff_text = email_template_body_text or ""
                else:
                    eff_html = campaign.body_html
                    # No explicit inline plain-text field on the modal yet —
                    # derive from HTML so Gmail's multipart fallback lands
                    # readable content, not blank.
                    eff_text = (
                        derive_plain_text(campaign.body_html)
                        if campaign.body_html
                        else (campaign.template or "")
                    )

                rendered_subject = render_subject(eff_subject, contact)
                rendered_html = render_body(eff_html, contact) if eff_html else None
                rendered_text = render_body(eff_text, contact) if eff_text else ""

                # Migration 0213 — sender-identity branch. OAuth path uses
                # the mailbox owner's user_id as sender_user_id (matches the
                # single-user compose path). SMTP path falls back to the
                # campaign creator — SMTP senders are org-shared identities,
                # not tied to a specific rep, so the campaign creator is the
                # closest "who authored this send" attribution we have.
                try:
                    if email_account is not None:
                        result = await send_email(
                            session,
                            org_id=campaign.org_id,
                            sender_user_id=email_account.user_id,
                            account_id=email_account.id,
                            contact_id=contact.id,
                            subject=rendered_subject,
                            body_text=rendered_text,
                            body_html=rendered_html,
                            reply_to=campaign.reply_to,
                        )
                    else:
                        assert email_smtp_sender is not None  # noqa: S101 — narrowed above
                        result = await send_email(
                            session,
                            org_id=campaign.org_id,
                            sender_user_id=campaign.created_by_id or uuid.UUID(int=0),
                            smtp_sender_id=email_smtp_sender.id,
                            contact_id=contact.id,
                            subject=rendered_subject,
                            body_text=rendered_text,
                            body_html=rendered_html,
                            reply_to=campaign.reply_to,
                        )
                except _HTTPExc as exc:
                    # tasks/email-reputation-warmup Step 6 — reputation
                    # gate raises 429 with a structured
                    # ``{skip_code, reason}`` detail. Prefix the error
                    # with the skip code so campaign progress logs can
                    # split by ``SKIPPED_*`` vs. other failure reasons.
                    # No new enum value — a skip counts as a soft failure
                    # that keeps the campaign moving through the batch.
                    skip_code = ""
                    if isinstance(exc.detail, dict):
                        raw_code = exc.detail.get("skip_code") if exc.detail else None
                        if raw_code:
                            skip_code = f"{raw_code}: "
                    logger.info(
                        "campaign email send rejected",
                        extra={"contact_id": str(cid), "skip_code": skip_code.rstrip(": ") or None},
                    )
                    await _mark_message(
                        session,
                        campaign_id=campaign_id,
                        contact_id=cid,
                        new_status=CampaignMessageStatus.failed,
                        error=(skip_code + str(exc.detail or "email send failed"))[:512],
                    )
                    continue
                except Exception as exc:  # provider-side transient failure
                    logger.exception("campaign email send failed", extra={"contact_id": str(cid)})
                    await _mark_message(
                        session,
                        campaign_id=campaign_id,
                        contact_id=cid,
                        new_status=CampaignMessageStatus.failed,
                        error=str(exc)[:512],
                    )
                    continue

                # send_email already persisted the Message row + logged the
                # activity + updated the conversation.last_message_at. All
                # we own is the CampaignMessage flip so stats + funnel land.
                await _mark_message(
                    session,
                    campaign_id=campaign_id,
                    contact_id=cid,
                    new_status=CampaignMessageStatus.sent,
                    channel_message_id=result.provider_message_id or str(result.message.id),
                    sent_at=result.message.sent_at or datetime.now(UTC),
                )
                continue

            # Find / create the (channel, external_id) conversation so the
            # outbound message also appears in the inbox.
            conversation = await _find_or_create_conversation(
                session,
                org_id=campaign.org_id,
                channel=campaign.channel,
                external_id=contact.phone,
                contact_id=contact.id,
            )

            # Template vs text branch (Step 3.5.6). `template_row` is set
            # iff this is a WA template campaign (loaded once before the
            # loop). `body` is what the inbox Message row records; for
            # template campaigns we synthesize a preview so the timeline
            # shows something meaningful even though Meta renders the
            # final text from approved template + parameters.
            #
            # Step 3.5.15 — per-org token-bucket acquire before each WA
            # send + single in-place retry on Meta 429.
            ref: ChannelMessageRef | None = None
            body = ""
            rate_retry_used = False
            send_error: Exception | None = None
            for _ in range(2):
                if campaign.channel == ConversationChannel.whatsapp:
                    from src.app.core.integrations.whatsapp.rate_limit import (
                        acquire_wa_rate_token,
                    )

                    await acquire_wa_rate_token(campaign.org_id, rate_per_sec=wa_rate_per_sec)
                try:
                    if template_row is not None:
                        # Start from the named-variable auto-resolution
                        # (`{{contact.first_name}}` → positional {1} etc.
                        # against the template's approved Meta body). Any
                        # operator-supplied static/field binding on the
                        # campaign row wins over the auto value for the
                        # same positional slot.
                        named_variables = _resolve_named_wa_variables(
                            template_row, contact, org, named_body_from_central
                        )
                        operator_variables = _resolve_template_variables(campaign, contact)
                        variables = {**named_variables, **operator_variables}
                        ref = await adapter.send_template(
                            org_id=campaign.org_id,
                            external_id=contact.phone,
                            template_name=template_row.name,
                            language=template_row.language,
                            variables=variables,
                            header_type=template_row.header_type,
                            header_text=template_row.header_text,
                        )
                        body = _preview_template_body(template_row, variables)
                    else:
                        body = _render_template(campaign.template or "", contact)
                        ref = await adapter.send(
                            org_id=campaign.org_id,
                            external_id=contact.phone,
                            text=body,
                            attachments=[],
                        )
                    send_error = None
                    break
                except WhatsAppRateLimited as rl_exc:
                    # Honour Meta's Retry-After and try the SAME contact
                    # once more. A second 429 means the token bucket isn't
                    # protecting hard enough — surface as a per-message
                    # failure so the chunk doesn't stall the rest.
                    if rate_retry_used:
                        send_error = rl_exc
                        break
                    rate_retry_used = True
                    import asyncio

                    await asyncio.sleep(rl_exc.retry_after_seconds)
                    continue
                except Exception as exc:  # adapter-side failure
                    send_error = exc
                    break

            if send_error is not None or ref is None:
                logger.exception("campaign send failed", extra={"contact_id": str(cid)})
                await _mark_message(
                    session,
                    campaign_id=campaign_id,
                    contact_id=cid,
                    new_status=CampaignMessageStatus.failed,
                    error=str(send_error or "send failed")[:512],
                )
                continue

            now = datetime.now(UTC)
            campaigns_da.add_outbound_message(
                session,
                Message(
                    org_id=campaign.org_id,
                    conversation_id=conversation.id,
                    direction=MessageDirection.out,
                    sender_user_id=campaign.created_by_id,
                    text=body,
                    attachments=[],
                    channel_message_id=ref.channel_message_id,
                    payload={"campaign_id": str(campaign.id)},
                    sent_at=ref.sent_at or now,
                ),
            )
            conversation.last_message_at = ref.sent_at or now
            await _mark_message(
                session,
                campaign_id=campaign_id,
                contact_id=cid,
                new_status=CampaignMessageStatus.sent,
                channel_message_id=ref.channel_message_id,
                sent_at=ref.sent_at or now,
                # Step 29 — stamp the A/B variant on the message row so
                # per-variant analytics can compute reply / read / click
                # rates without joining back to the campaign config.
                variant=assigned_variant,
            )
        except Exception as exc:
            # Unexpected error outside the adapter call (DB, lookup,
            # rendering). Fail this one row and restart the chunk on a
            # clean session — rollback expires every loaded object.
            logger.exception("campaign contact dispatch failed", extra={"contact_id": str(cid)})
            await session.rollback()
            await _mark_message(
                session,
                campaign_id=campaign_id,
                contact_id=cid,
                new_status=CampaignMessageStatus.failed,
                error=str(exc)[:512] or "send failed",
            )
            raise _ChunkRestart from exc


async def _find_or_create_conversation(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    channel: ConversationChannel,
    external_id: str,
    contact_id: uuid.UUID,
) -> Conversation:
    existing = await campaigns_da.get_conversation_by_external_id(
        session, org_id=org_id, channel=channel, external_id=external_id
    )
    if existing is not None:
        return existing
    conv = campaigns_da.add_conversation(
        session,
        Conversation(
            org_id=org_id,
            channel=channel,
            external_id=external_id,
            contact_id=contact_id,
        ),
    )
    await session.flush()
    return conv


async def _mark_message(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    contact_id: uuid.UUID,
    new_status: CampaignMessageStatus,
    channel_message_id: str | None = None,
    error: str | None = None,
    sent_at: datetime | None = None,
    variant: str | None = None,
) -> None:
    row = await campaigns_da.get_campaign_message_for_contact(
        session, campaign_id=campaign_id, contact_id=contact_id
    )
    if row is None:
        return
    row.status = new_status
    if channel_message_id is not None:
        row.channel_message_id = channel_message_id
    if error is not None:
        row.error = error
    if sent_at is not None:
        row.sent_at = sent_at
    # Step 29 — only stamp the variant when explicitly passed in.
    # Leaves the legacy NULL state untouched for non-A/B campaigns +
    # for the post-winner phase where everyone gets the winning
    # template directly.
    if variant is not None:
        row.variant = variant
    await session.commit()


def _assign_ab_variant(
    *,
    campaign_id: uuid.UUID,
    contact_id: uuid.UUID,
    split_ratio: int,
) -> str:
    """Step 29 — deterministic per-(campaign, contact) variant pick.

    Hashes the pair into a 0–99 bucket; recipients in the first
    ``split_ratio`` slots get A, the rest B. Deterministic so a
    re-run of the same chunk (e.g. retry after a worker crash)
    re-assigns the same contact to the same variant — keeps the
    split honest even under retries. ``split_ratio`` of 0 sends
    every recipient to B; 100 sends every recipient to A — both
    valid edge cases the operator can set on the create modal."""
    import hashlib

    h = hashlib.sha256(f"{campaign_id}:{contact_id}".encode()).digest()
    bucket = h[0] % 100
    return "A" if bucket < max(0, min(100, split_ratio)) else "B"


_TEMPLATE_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _render_template(template: str, contact: Contact) -> str:
    """Tiny Mustache-style substitution.

    Supports `{{full_name}}`, `{{phone}}`, `{{email}}`. Unknown
    variables are left intact (rather than raising) so a typo doesn't
    blow up the whole chunk.
    """
    fields = {
        "full_name": contact.full_name,
        "phone": contact.phone or "",
        "email": contact.email or "",
    }

    def _sub(match: re.Match[str]) -> str:
        return fields.get(match.group(1), match.group(0))

    return _TEMPLATE_VAR_RE.sub(_sub, template)


# --- Step 3.5.6: template variable resolution + preview -----------------


# Fallback string used when a `kind=field` binding resolves to empty
# (missing full_name, etc.). Meta rejects template messages whose body
# parameters are empty strings — surfacing a generic placeholder keeps
# delivery healthy. Per-template configurable fallbacks are P2 work.
_TEMPLATE_FIELD_FALLBACK = "Customer"


def _get_contact_field(contact: Contact, field_name: str) -> str:
    """Resolve a `kind=field` binding's target against the contact.
    Returns "" (empty) when the field is missing — caller substitutes
    the fallback string (`_TEMPLATE_FIELD_FALLBACK`).

    Supported fields:
      - `full_name`, `phone`, `email`
      - `custom_data.<key>` — pulls from the JSONB column

    Unknown field names return "" (treated as missing); the picker
    only surfaces known fields, so this is a defensive default
    rather than a user-reachable code path."""
    if field_name == "full_name":
        return contact.full_name or ""
    if field_name == "phone":
        return contact.phone or ""
    if field_name == "email":
        return contact.email or ""
    if field_name.startswith("custom_data."):
        key = field_name.split(".", 1)[1]
        custom = getattr(contact, "custom_data", None) or {}
        value = custom.get(key)
        return str(value) if value not in (None, "") else ""
    return ""


def _extract_named_body_from_components(
    template_row: WhatsAppTemplate,
) -> str | None:
    """Pull the ORIGINAL named-variable BODY text out of
    ``template_row.body_components``.

    Rationale: ``template_row.body`` gets overwritten by the sync-from-
    Meta job with Meta's positional copy (``{{1}}``, ``{{2}}``), so
    running ``convert_to_positional`` on it recovers nothing. The
    ``body_components`` column, populated at submit-time, still carries
    the pre-conversion named text (``{{contact.first_name}}``).

    Returns None when ``body_components`` is missing/empty or has no
    BODY entry — caller falls back to the central-library row.
    """
    comps = template_row.body_components
    if not isinstance(comps, list):
        return None
    for comp in comps:
        if not isinstance(comp, dict):
            continue
        if str(comp.get("type") or "").upper() == "BODY":
            text = comp.get("text")
            if isinstance(text, str) and text.strip():
                return text
    return None


def _resolve_named_wa_variables(
    template_row: WhatsAppTemplate,
    contact: Contact,
    org: Organization | None,
    named_body_override: str | None = None,
) -> dict[int, str]:
    """Derive Meta positional params (``{1: ..., 2: ...}``) from the
    CRM template's named variables (``{{contact.first_name}}``,
    ``{{org.name}}``, etc.) resolved against the target contact.

    Meta only accepts positional placeholders in the actual template
    body, so ``convert_all_components`` rewrites the CRM body at
    Meta-submit time. At send-time we re-run the same conversion —
    but against the ORIGINAL named body (from ``body_components`` or
    the central-library row), never ``template_row.body`` which the
    Meta sync overwrites with the positional copy.

    Source resolution order:
      1. ``named_body_override`` if the caller supplied one (usually
         the central-library ``body_text`` fetched once per chunk).
      2. The BODY entry inside ``template_row.body_components``.

    Returns an empty dict when neither source yields a body with
    named vars (pure positional or vars-free template).
    """
    from src.app.core.integrations.whatsapp.meta_variables import (
        convert_to_positional,
    )

    named_body = named_body_override or _extract_named_body_from_components(template_row)
    if not named_body:
        return {}

    _, param_names = convert_to_positional(named_body)
    if not param_names:
        return {}

    context = _build_wa_variable_context(contact, org)
    resolved: dict[int, str] = {}
    for idx, name in enumerate(param_names, start=1):
        value = _resolve_dotted_path(context, name)
        text = "" if value is None else str(value)
        # Meta rejects empty positional params — fall back so the send
        # succeeds even when a contact's field is blank (e.g. no
        # ``full_name``). Matches the modal's "field → fallback"
        # convention for operator-supplied bindings.
        resolved[idx] = text if text.strip() else _TEMPLATE_FIELD_FALLBACK
    return resolved


def _build_wa_variable_context(contact: Contact, org: Organization | None) -> dict[str, Any]:
    """Build the nested dict the WA variable resolver reads. Mirrors
    :func:`core.templates.render.build_context` but derives
    ``contact.first_name`` / ``last_name`` from ``full_name`` (the
    Contact model stores a single ``full_name`` column), so templates
    that reference ``{{contact.first_name}}`` render without an extra
    schema lookup.
    """
    full_name = contact.full_name or ""
    parts = full_name.split(None, 1) if full_name else []
    first_name = parts[0] if parts else ""
    last_name = parts[1] if len(parts) > 1 else ""
    return {
        "contact": {
            "id": str(contact.id),
            "first_name": first_name,
            "last_name": last_name,
            "full_name": full_name,
            "email": contact.email or "",
            "phone": contact.phone or "",
            "source": getattr(contact, "source", None) or "",
            "custom_data": dict(getattr(contact, "custom_data", None) or {}),
        },
        "org": {
            "name": getattr(org, "name", "") if org else "",
            "support_email": getattr(org, "support_email", "") if org else "",
        },
    }


def _resolve_dotted_path(context: dict[str, Any], path: str) -> Any:
    """Walk a dot-scoped path (``contact.first_name``) through a nested
    dict, returning ``None`` for any missing segment."""
    cur: Any = context
    for segment in path.split("."):
        if not isinstance(cur, dict) or segment not in cur:
            return None
        cur = cur[segment]
    return cur


def _resolve_template_variables(campaign: Campaign, contact: Contact) -> dict[int, str]:
    """Turn `campaign.template_variables` JSONB into a flat `{n: str}`
    dict the adapter's `send_template` consumes.

    Per-binding behaviour:
      - `kind='static'` → `value` verbatim.
      - `kind='field'`  → contact attribute lookup; empty → fallback
        to "Customer" (option (b) per Step 3.5.6 design).

    The picker pre-validated that every `{{n}}` in the template body
    has a binding, so this function trusts the JSONB shape and skips
    template-body re-parsing."""
    bindings: dict[str, Any] = campaign.template_variables or {}
    resolved: dict[int, str] = {}
    for key, binding in bindings.items():
        try:
            n = int(key)
        except (TypeError, ValueError):
            # Defensive: skip malformed keys rather than raise. Picker
            # validates int keys, so this is "should never happen".
            continue
        if not isinstance(binding, dict):
            continue
        kind = binding.get("kind")
        value = binding.get("value", "")
        if kind == "static":
            resolved[n] = str(value)
        elif kind == "field":
            raw = _get_contact_field(contact, str(value))
            resolved[n] = raw if raw else _TEMPLATE_FIELD_FALLBACK
    return resolved


# --- Step 3.5.12: Meta webhook status updates ---------------------------


# Map Meta's status strings → our `CampaignMessageStatus` enum +
# which timestamp column to stamp. `sent` is intentionally a no-op
# here: the dispatch path already stamps `sent_at` + `status='sent'`
# when the outbound POST returns 200, and Meta's `sent` echo is
# redundant.
_META_STATUS_TO_LOCAL: dict[str, tuple[CampaignMessageStatus | None, str | None]] = {
    "sent": (None, None),
    "delivered": (CampaignMessageStatus.delivered, "delivered_at"),
    "read": (CampaignMessageStatus.read, "read_at"),
    "failed": (CampaignMessageStatus.failed, None),
}


async def apply_meta_status(
    session: AsyncSession,
    *,
    channel_message_id: str,
    meta_status: str,
    timestamp: datetime,
    error: str | None = None,
) -> bool:
    """Update the `CampaignMessage` row keyed by Meta's
    `channel_message_id` to reflect the lifecycle event.

    Status flow is forward-only (lower → higher): we don't downgrade
    a `read` row to `delivered` if a delayed event arrives, and we
    don't overwrite an existing `failed` status with a later
    `delivered`. Timestamps are stamped on the first event of their
    kind (later events ignored — Meta occasionally re-sends).

    Returns True when a row was actually updated; False otherwise
    (unknown message id — likely an outbound that didn't originate
    from our campaigns engine, e.g. a manual reply from the inbox).
    """
    if not channel_message_id:
        return False
    mapping = _META_STATUS_TO_LOCAL.get(meta_status)
    if mapping is None:
        # Unknown Meta status; nothing to do but don't crash.
        return False

    row = await campaigns_da.get_campaign_message_by_channel_id(session, channel_message_id)
    if row is None:
        return False

    # `failed` is terminal — any later non-failed event (delivered,
    # read) is ignored entirely, including timestamps. Meta sometimes
    # re-sends status events out of order; this guard keeps the row's
    # error stable and prevents misleading "delivered after failed"
    # signals in the UI.
    if row.status == CampaignMessageStatus.failed and meta_status != "failed":
        return False

    new_status, ts_column = mapping
    changed = False

    # Status: forward-only. The enum order in our model is
    # queued < sent < delivered < read < failed (failed is terminal).
    _ORDER = {
        CampaignMessageStatus.queued: 0,
        CampaignMessageStatus.sent: 1,
        CampaignMessageStatus.delivered: 2,
        CampaignMessageStatus.read: 3,
        # `failed` is terminal — never overwritten by a later success.
        CampaignMessageStatus.failed: 99,
    }
    if (
        new_status is not None
        and row.status != CampaignMessageStatus.failed
        and _ORDER.get(new_status, 0) > _ORDER.get(row.status, 0)
    ):
        row.status = new_status
        changed = True

    if ts_column is not None and getattr(row, ts_column) is None:
        setattr(row, ts_column, timestamp)
        changed = True

    if meta_status == "failed" and error and row.error is None:
        row.error = error[:512]
        changed = True

    if changed:
        await session.commit()
    return changed


# --- Campaigns v1 Step 05: Email tracking status callbacks ---------------


# Map Email tracking events → the target CampaignMessage.status +
# timestamp column. ``delivered`` uses the existing WA-side column so
# both channels can be aggregated with a single query. ``opened`` +
# ``clicked`` are Email-only states added in migration 0153.
_EMAIL_STATUS_TO_LOCAL: dict[str, tuple[CampaignMessageStatus | None, str | None]] = {
    "delivered": (CampaignMessageStatus.delivered, "delivered_at"),
    "opened": (CampaignMessageStatus.opened, "opened_at"),
    "clicked": (CampaignMessageStatus.clicked, "first_click_at"),
    "bounced": (CampaignMessageStatus.failed, "bounced_at"),
    "unsubscribed": (None, "unsubscribed_at"),
}


_EMAIL_STATUS_ORDER: dict[CampaignMessageStatus, int] = {
    CampaignMessageStatus.queued: 0,
    CampaignMessageStatus.sent: 1,
    CampaignMessageStatus.delivered: 2,
    CampaignMessageStatus.opened: 3,
    CampaignMessageStatus.clicked: 4,
    CampaignMessageStatus.read: 3,  # WA-only, ranked alongside opened
    CampaignMessageStatus.failed: 99,
}


async def apply_email_status(
    session: AsyncSession,
    *,
    channel_message_id: str,
    email_status: str,
    timestamp: datetime,
    bounce_type: str | None = None,
    error: str | None = None,
) -> bool:
    """Update the ``CampaignMessage`` row keyed by the outbound email's
    provider message id to reflect a lifecycle event.

    ``email_status`` is one of ``delivered`` / ``opened`` / ``clicked`` /
    ``bounced`` / ``unsubscribed``. Status is forward-only + set-once
    (the same webhook / sync event arriving twice is a no-op). Bounces
    move the row to ``failed`` with the ``bounce_type`` classifier
    (``hard`` / ``soft`` / ``spam_complaint``) stored alongside the
    timestamp so the UI can distinguish permanent-suppress bounces from
    retry-able soft ones. ``unsubscribed`` only stamps the timestamp —
    Step 06 will populate this via the campaign footer link handler.

    Returns True when a row was actually updated; False otherwise
    (unknown message id, unknown status, or the event was already
    recorded).
    """
    if not channel_message_id:
        return False
    mapping = _EMAIL_STATUS_TO_LOCAL.get(email_status)
    if mapping is None:
        return False

    row = await campaigns_da.get_campaign_message_by_channel_id(session, channel_message_id)
    if row is None:
        return False

    # `failed` is terminal for the status flip — but bounce events on
    # an already-failed row still stamp bounced_at + bounce_type so the
    # UI can show why (e.g. the send succeeded then bounced back).
    is_bounce = email_status == "bounced"
    if (
        row.status == CampaignMessageStatus.failed
        and not is_bounce
        and email_status != "unsubscribed"
    ):
        return False

    new_status, ts_column = mapping
    changed = False

    if new_status is not None and _EMAIL_STATUS_ORDER.get(new_status, 0) > _EMAIL_STATUS_ORDER.get(
        row.status, 0
    ):
        row.status = new_status
        changed = True

    if ts_column is not None and getattr(row, ts_column) is None:
        setattr(row, ts_column, timestamp)
        changed = True

    if is_bounce:
        if row.bounce_type is None and bounce_type:
            row.bounce_type = bounce_type
            changed = True
        if row.error is None:
            row.error = (error or f"email bounced ({bounce_type or 'hard'})")[:512]
            changed = True

    if changed:
        await session.commit()
    return changed


def _preview_template_body(template_row: WhatsAppTemplate, variables: dict[int, str]) -> str:
    """Substitute resolved variables into the template body for the
    inbox Message row's `text`. Meta renders the final message
    server-side from the approved template + parameters — this preview
    is what the operator + contact-timeline UI display.

    Mirrors Meta's positional substitution: `{{1}}` → variables[1] etc.
    Unfilled placeholders pass through unchanged (defensive — picker
    validation should prevent this)."""

    def _sub(match: re.Match[str]) -> str:
        n = int(match.group(1))
        return variables.get(n, match.group(0))

    return re.sub(r"\{\{(\d+)\}\}", _sub, template_row.body or "")


# --- stats --------------------------------------------------------------


async def list_messages(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    status_filter: CampaignMessageStatus | None = None,
    page: int = 1,
    size: int = 100,
) -> tuple[list[CampaignMessage], int]:
    """Per-message rows for a campaign's detail view."""
    await get_campaign(session, campaign_id)

    total = await campaigns_da.count_messages_filtered(
        session, campaign_id=campaign_id, status_filter=status_filter
    )
    offset = (page - 1) * size
    rows = await campaigns_da.list_messages_page(
        session,
        campaign_id=campaign_id,
        status_filter=status_filter,
        offset=offset,
        limit=size,
    )
    return rows, total


async def retry_message(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    message_id: uuid.UUID,
) -> CampaignMessage:
    """Re-dispatch one failed `CampaignMessage`. Flips status back to
    `queued` first so a concurrent reader sees the transition, then
    runs the single-contact dispatch inline."""
    await get_campaign(session, campaign_id)

    msg = ensure_found(
        await campaigns_da.get_campaign_message_in_campaign(
            session, campaign_id=campaign_id, message_id=message_id
        ),
        entity="campaign message",
    )
    if msg.status != CampaignMessageStatus.failed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot retry a {msg.status.value} message",
        )
    msg.status = CampaignMessageStatus.queued
    msg.error = None
    await session.commit()

    await dispatch_chunk(session, campaign_id=campaign_id, contact_ids=[msg.contact_id])
    await session.refresh(msg)
    return msg


async def dashboard_stats(session: AsyncSession) -> dict[str, Any]:
    """Org-wide campaign KPIs for the current calendar month.

    Aggregates every `CampaignMessage` whose `sent_at` falls in the
    caller's this-month window and returns raw counts plus the two
    rates the dashboard cards render. Rates are `None` (rendered as
    "—" client-side) when the denominator is zero so we never show
    a fake `0%` before any campaign has run.
    """
    now = datetime.now(UTC)
    start_of_month = datetime(now.year, now.month, 1, tzinfo=UTC)
    counts = await campaigns_da.dashboard_stats_since(session, since=start_of_month)
    sent = counts["sent"]
    delivered = counts["delivered"]
    read = counts["read"]
    delivery_rate = (delivered / sent) if sent else None
    read_rate = (read / delivered) if delivered else None
    return {
        "since": start_of_month,
        "sent": sent,
        "delivered": delivered,
        "read": read,
        "delivery_rate": delivery_rate,
        "read_rate": read_rate,
    }


async def stats(session: AsyncSession, *, campaign_id: uuid.UUID) -> dict[str, Any]:
    campaign = await get_campaign(session, campaign_id)
    rows = await campaigns_da.stats_by_status(session, campaign_id=campaign_id)
    by_status: dict[str, int] = {r[0].value: r[1] for r in rows}
    audience_size = sum(by_status.values())
    # Campaigns v1 Step 05 — Email tracking counters. ``bounced`` +
    # ``unsubscribed`` don't live in the status enum (they're
    # ``failed`` rows with a bounce_type / unsubscribed_at set); we
    # count them via dedicated column-presence tallies so the funnel
    # can render the classifier split without a second endpoint.
    tracking = await campaigns_da.email_tracking_counts(session, campaign_id=campaign_id)
    return {
        "campaign_id": campaign.id,
        "status": campaign.status,
        "audience_size": audience_size,
        "queued": by_status.get("queued", 0),
        "sent": by_status.get("sent", 0),
        "delivered": by_status.get("delivered", 0),
        "read": by_status.get("read", 0),
        "failed": by_status.get("failed", 0),
        "opened": by_status.get("opened", 0),
        "clicked": by_status.get("clicked", 0),
        "bounced": tracking.get("bounced", 0),
        "unsubscribed": tracking.get("unsubscribed", 0),
    }


# --- snapshots ----------------------------------------------------------


_SNAPSHOT_FIELDS = (
    "id",
    "name",
    "channel",
    "status",
    "audience_filter",
)


def _snapshot(c: Campaign) -> dict[str, Any]:
    return snapshot(c, fields=_SNAPSHOT_FIELDS)


__all__ = [
    "CHUNK_SIZE",
    "apply_meta_status",
    "create_campaign",
    "delete_campaign",
    "dispatch_chunk",
    "enqueue",
    "get_campaign",
    "list_campaigns",
    "list_messages",
    "resolve_audience",
    "retry_message",
    "stats",
    "update_campaign",
]
