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
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit, data_access
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
    resolve as resolve_channel,
)
from src.app.core.integrations.whatsapp.models import WhatsAppTemplate
from src.app.shared.audit import log_entity_change, snapshot
from src.app.shared.db.queries import ensure_found, get_or_404

logger = logging.getLogger(__name__)

CHUNK_SIZE = 50


# --- reads ---------------------------------------------------------------


async def list_campaigns(
    session: AsyncSession, *, page: int = 1, size: int = 50
) -> tuple[list[Campaign], int]:
    total = (
        await session.execute(select(func.count()).select_from(Campaign))
    ).scalar_one()
    offset = (page - 1) * size
    rows = (
        (
            await session.execute(
                select(Campaign)
                .order_by(Campaign.created_at.desc())
                .offset(offset)
                .limit(size)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


async def get_campaign(
    session: AsyncSession, campaign_id: uuid.UUID
) -> Campaign:
    return await get_or_404(session, Campaign, campaign_id, entity="campaign")


# --- writes --------------------------------------------------------------


async def create_campaign(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: CampaignCreate,
) -> Campaign:
    campaign = Campaign(
        org_id=org_id,
        name=payload.name,
        channel=payload.channel,
        audience_filter=payload.audience_filter.model_dump(exclude_none=True),
        template=payload.template,
        template_id=payload.template_id,
        template_variables=(
            {k: v.model_dump() for k, v in payload.template_variables.items()}
            if payload.template_variables is not None
            else None
        ),
        schedule_at=payload.schedule_at,
        status=CampaignStatus.draft,
        created_by_id=user_id,
    )
    session.add(campaign)
    await session.commit()
    await session.refresh(campaign)
    await log_entity_change(
        action="campaigns.created",
        entity_type="campaign",
        entity_id=campaign.id,
        after=_snapshot(campaign),
    )
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
            exclude_none=True
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


async def delete_campaign(
    session: AsyncSession, *, campaign_id: uuid.UUID
) -> None:
    campaign = await get_campaign(session, campaign_id)
    if campaign.status not in (CampaignStatus.draft, CampaignStatus.failed):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot delete a {campaign.status.value} campaign",
        )
    before = _snapshot(campaign)
    await session.delete(campaign)
    await session.commit()
    await log_entity_change(
        action="campaigns.deleted",
        entity_type="campaign",
        entity_id=campaign_id,
        before=before,
    )


# --- audience -----------------------------------------------------------


async def resolve_audience(
    session: AsyncSession, *, audience_filter: dict[str, Any]
) -> list[uuid.UUID]:
    """Translate the campaign's `audience_filter` JSONB into a list of
    contact ids. Three modes per `AudienceFilter`:

      - Empty filter → every contact in the org (RLS handles isolation).
      - `group_id` set → delegate to `contact_groups.resolve_group_contacts`
        which honours static-vs-dynamic group semantics.
      - `q/source/tag` set → run the predicate directly.

    A campaign that references a deleted group resolves to an empty
    list — the dispatch path then marks all queued messages failed
    with a clear "audience empty" error rather than silently sending
    zero messages."""
    af = AudienceFilter.model_validate(audience_filter or {})

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

    # Filter mode (q / source / tag) — falls through to "" empty
    # filter = "everyone" by intentional design.
    filters: list[Any] = []
    if af.q:
        like = f"%{af.q}%"
        from sqlalchemy import or_

        filters.append(
            or_(
                Contact.full_name.ilike(like),
                Contact.phone.ilike(like),
                Contact.email.ilike(like),
            )
        )
    if af.source:
        filters.append(Contact.source == af.source)
    if af.tag:
        filters.append(Contact.tags.contains([af.tag]))

    where = and_(*filters) if filters else None
    stmt = select(Contact.id)
    if where is not None:
        stmt = stmt.where(where)
    return [row for (row,) in (await session.execute(stmt)).all()]


# --- start + dispatch ----------------------------------------------------


async def enqueue(
    session: AsyncSession, *, campaign_id: uuid.UUID
) -> dict[str, Any]:
    """Resolve audience → split into chunks → dispatch Celery tasks.

    Returns a small summary the router echoes back to the operator
    (audience_size + chunks_enqueued + scheduled_at).
    """
    campaign = await get_campaign(session, campaign_id)
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
            await resolve_whatsapp_adapter(session)
        else:
            resolve_channel(campaign.channel)
    except (ChannelNotRegistered, WhatsAppNotConnected) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    contact_ids = await resolve_audience(
        session, audience_filter=campaign.audience_filter
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
    now = datetime.now(timezone.utc)
    is_scheduled = (
        campaign.schedule_at is not None and campaign.schedule_at > now
    )
    campaign.status = (
        CampaignStatus.scheduled if is_scheduled else CampaignStatus.running
    )
    await session.commit()

    chunks = [
        contact_ids[i : i + CHUNK_SIZE]
        for i in range(0, len(contact_ids), CHUNK_SIZE)
    ]

    # Pre-queue placeholder rows so stats immediately reflect "queued: N".
    for chunk in chunks:
        await _queue_chunk_rows(
            session, campaign_id=campaign.id, contact_ids=chunk
        )

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
        from src.app.core.campaigns.tasks import (
            HAS_CELERY,
            send_campaign_chunk,
        )

        from config import CELERY_ENABLED as _CELERY_ENABLED

        if HAS_CELERY and _CELERY_ENABLED:
            for chunk in chunks:
                send_campaign_chunk.delay(
                    str(campaign.id),
                    [str(c) for c in chunk],
                )
        else:
            for chunk in chunks:
                await dispatch_chunk(
                    session, campaign_id=campaign.id, contact_ids=chunk
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
    await session.execute(
        pg_insert(CampaignMessage)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=["campaign_id", "contact_id"]
        )
    )
    await session.commit()


# --- the actual sender (called from the Celery task) ---------------------


async def dispatch_chunk(
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
            adapter = await resolve_whatsapp_adapter(session)
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

    # Template campaigns (Step 3.5.6): load the WhatsAppTemplate row
    # once per chunk so the loop doesn't re-query for every contact.
    # If the template was deleted from local cache between campaign
    # creation and dispatch (Step 3.5.4 hard-delete on sync), every
    # queued row in this chunk fails with a clear error — the row's
    # ON DELETE SET NULL FK kept the campaign intact, but there's
    # nothing to send.
    template_row: WhatsAppTemplate | None = None
    if campaign.template_id is not None:
        template_row = (
            await session.execute(
                select(WhatsAppTemplate).where(
                    WhatsAppTemplate.id == campaign.template_id
                )
            )
        ).scalar_one_or_none()
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

        bundle = await get_active_config(session)
        if bundle is not None:
            _, _wa_config = bundle
            wa_rate_per_sec = max(1, int(_wa_config.rate_limit_per_sec or 50))

    for cid in contact_ids:
        contact = await data_access.get_contact(session, cid)
        if contact is None or not contact.phone:
            await _mark_message(
                session,
                campaign_id=campaign_id,
                contact_id=cid,
                new_status=CampaignMessageStatus.failed,
                error="contact has no phone for this channel",
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

                await acquire_wa_rate_token(
                    campaign.org_id, rate_per_sec=wa_rate_per_sec
                )
            try:
                if template_row is not None:
                    variables = _resolve_template_variables(campaign, contact)
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
            logger.exception(
                "campaign send failed", extra={"contact_id": str(cid)}
            )
            await _mark_message(
                session,
                campaign_id=campaign_id,
                contact_id=cid,
                new_status=CampaignMessageStatus.failed,
                error=str(send_error or "send failed")[:512],
            )
            continue

        now = datetime.now(timezone.utc)
        session.add(
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
            )
        )
        conversation.last_message_at = ref.sent_at or now
        await _mark_message(
            session,
            campaign_id=campaign_id,
            contact_id=cid,
            new_status=CampaignMessageStatus.sent,
            channel_message_id=ref.channel_message_id,
            sent_at=ref.sent_at or now,
        )

    # If this was the last queued chunk, flip the campaign to `done`.
    pending = (
        await session.execute(
            select(func.count())
            .select_from(CampaignMessage)
            .where(CampaignMessage.campaign_id == campaign_id)
            .where(CampaignMessage.status == CampaignMessageStatus.queued)
        )
    ).scalar_one()
    if (pending or 0) == 0 and campaign.status == CampaignStatus.running:
        campaign.status = CampaignStatus.done
        await session.commit()


async def _find_or_create_conversation(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    channel: ConversationChannel,
    external_id: str,
    contact_id: uuid.UUID,
) -> Conversation:
    existing = (
        await session.execute(
            select(Conversation)
            .where(Conversation.channel == channel)
            .where(Conversation.external_id == external_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    conv = Conversation(
        org_id=org_id,
        channel=channel,
        external_id=external_id,
        contact_id=contact_id,
    )
    session.add(conv)
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
) -> None:
    row = (
        await session.execute(
            select(CampaignMessage)
            .where(CampaignMessage.campaign_id == campaign_id)
            .where(CampaignMessage.contact_id == contact_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return
    row.status = new_status
    if channel_message_id is not None:
        row.channel_message_id = channel_message_id
    if error is not None:
        row.error = error
    if sent_at is not None:
        row.sent_at = sent_at
    await session.commit()


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


def _resolve_template_variables(
    campaign: Campaign, contact: Contact
) -> dict[int, str]:
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
    "sent":      (None, None),
    "delivered": (CampaignMessageStatus.delivered, "delivered_at"),
    "read":      (CampaignMessageStatus.read, "read_at"),
    "failed":    (CampaignMessageStatus.failed, None),
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

    row = (
        await session.execute(
            select(CampaignMessage).where(
                CampaignMessage.channel_message_id == channel_message_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False

    # `failed` is terminal — any later non-failed event (delivered,
    # read) is ignored entirely, including timestamps. Meta sometimes
    # re-sends status events out of order; this guard keeps the row's
    # error stable and prevents misleading "delivered after failed"
    # signals in the UI.
    if (
        row.status == CampaignMessageStatus.failed
        and meta_status != "failed"
    ):
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


def _preview_template_body(
    template_row: WhatsAppTemplate, variables: dict[int, str]
) -> str:
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
    status_filter: "CampaignMessageStatus | None" = None,
    page: int = 1,
    size: int = 100,
) -> tuple[list[CampaignMessage], int]:
    """Per-message rows for a campaign's detail view."""
    await get_campaign(session, campaign_id)

    filters: list[Any] = [CampaignMessage.campaign_id == campaign_id]
    if status_filter is not None:
        filters.append(CampaignMessage.status == status_filter)
    where = and_(*filters)

    total = (
        await session.execute(
            select(func.count()).select_from(CampaignMessage).where(where)
        )
    ).scalar_one()
    offset = (page - 1) * size
    rows = (
        (
            await session.execute(
                select(CampaignMessage)
                .where(where)
                .order_by(CampaignMessage.created_at.asc())
                .offset(offset)
                .limit(size)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


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
        (
            await session.execute(
                select(CampaignMessage)
                .where(CampaignMessage.id == message_id)
                .where(CampaignMessage.campaign_id == campaign_id)
            )
        ).scalar_one_or_none(),
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

    await dispatch_chunk(
        session, campaign_id=campaign_id, contact_ids=[msg.contact_id]
    )
    await session.refresh(msg)
    return msg


async def stats(
    session: AsyncSession, *, campaign_id: uuid.UUID
) -> dict[str, Any]:
    campaign = await get_campaign(session, campaign_id)
    rows = (
        await session.execute(
            select(CampaignMessage.status, func.count(CampaignMessage.id))
            .where(CampaignMessage.campaign_id == campaign_id)
            .group_by(CampaignMessage.status)
        )
    ).all()
    by_status: dict[str, int] = {r[0].value: int(r[1]) for r in rows}
    audience_size = sum(by_status.values())
    return {
        "campaign_id": campaign.id,
        "status": campaign.status,
        "audience_size": audience_size,
        "queued": by_status.get("queued", 0),
        "sent": by_status.get("sent", 0),
        "delivered": by_status.get("delivered", 0),
        "read": by_status.get("read", 0),
        "failed": by_status.get("failed", 0),
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
