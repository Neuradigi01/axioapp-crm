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

from src.app.core import audit
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
    row = (
        await session.execute(
            select(Campaign).where(Campaign.id == campaign_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="campaign not found",
        )
    return row


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
        schedule_at=payload.schedule_at,
        status=CampaignStatus.draft,
        created_by_id=user_id,
    )
    session.add(campaign)
    await session.commit()
    await session.refresh(campaign)
    await audit.log(
        "campaigns.created",
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
        changed = True
    if payload.schedule_at is not None:
        campaign.schedule_at = payload.schedule_at
        changed = True
    if changed:
        await session.commit()
        await session.refresh(campaign)
        await audit.log(
            "campaigns.updated",
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
    await audit.log(
        "campaigns.deleted",
        entity_type="campaign",
        entity_id=campaign_id,
        before=before,
    )


# --- audience -----------------------------------------------------------


async def resolve_audience(
    session: AsyncSession, *, audience_filter: dict[str, Any]
) -> list[uuid.UUID]:
    """Translate a `{q, source, tag}` filter into a list of contact ids."""
    af = AudienceFilter.model_validate(audience_filter or {})

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
    # Adapter must exist before we accept the start request.
    try:
        resolve_channel(campaign.channel)
    except ChannelNotRegistered as exc:
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

    # Dispatch the chunks. Today we run them inline (one POST per
    # contact per chunk, sequentially) because Celery isn't wired into
    # this build. The architecture stays sound: a future swap to
    # `send_campaign_chunk.delay(...)` (Celery task) replaces just
    # this loop — chunk size, audience resolver, and per-message
    # persistence don't change.
    #
    # Scheduled-for-future campaigns stay in `status='scheduled'`
    # with their queued rows pre-inserted; an operator can flip back
    # to draft + re-start to force a now-send. A periodic scheduler
    # (Celery beat, in production) will pick up the eta'd ones.
    if not is_scheduled:
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
    try:
        adapter = resolve_channel(campaign.channel)
    except ChannelNotRegistered as exc:
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

    for cid in contact_ids:
        contact = (
            await session.execute(select(Contact).where(Contact.id == cid))
        ).scalar_one_or_none()
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

        body = _render_template(campaign.template, contact)
        try:
            ref: ChannelMessageRef = await adapter.send(
                org_id=campaign.org_id,
                external_id=contact.phone,
                text=body,
                attachments=[],
            )
        except Exception as exc:  # adapter-side failure
            logger.exception("campaign send failed", extra={"contact_id": str(cid)})
            await _mark_message(
                session,
                campaign_id=campaign_id,
                contact_id=cid,
                new_status=CampaignMessageStatus.failed,
                error=str(exc)[:512],
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

    msg = (
        await session.execute(
            select(CampaignMessage)
            .where(CampaignMessage.id == message_id)
            .where(CampaignMessage.campaign_id == campaign_id)
        )
    ).scalar_one_or_none()
    if msg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="campaign message not found",
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


def _snapshot(c: Campaign) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "name": c.name,
        "channel": c.channel.value,
        "status": c.status.value,
        "audience_filter": c.audience_filter,
    }


__all__ = [
    "CHUNK_SIZE",
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
