"""Data-access layer for the campaigns module.

Pure query helpers — no transactions, no audit. Leaf module; never
imports a `service.py`.

Step 11 of ``tasks/template-library`` switched
``tbl_campaigns.template_id`` (and the A/B variants) from WA-template
UUIDs to central ``tbl_message_templates.id`` values. The dispatcher
still needs the Meta-specific extension row (header type, language,
button payloads) at send time — `get_wa_extension_for_campaign_template`
resolves it via the Step-9 reciprocal link.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.campaigns.models import (
    Campaign,
    CampaignMessage,
    CampaignMessageStatus,
)
from src.app.core.contacts.models import Contact
from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    Message,
)
from src.app.core.integrations.whatsapp.models import WhatsAppTemplate


async def get_wa_extension_for_campaign_template(
    session: AsyncSession, central_template_id: uuid.UUID
) -> WhatsAppTemplate | None:
    """Given the central row's UUID, return its WhatsApp extension row."""
    result = await session.execute(
        select(WhatsAppTemplate).where(
            WhatsAppTemplate.message_template_id == central_template_id
        )
    )
    return result.scalar_one_or_none()


async def get_wa_extensions_for_template_ids(
    session: AsyncSession, central_template_ids: list[uuid.UUID]
) -> dict[uuid.UUID, WhatsAppTemplate]:
    """Bulk-lookup WhatsApp extension rows keyed by central template id."""
    if not central_template_ids:
        return {}
    rows = (
        await session.execute(
            select(WhatsAppTemplate).where(
                WhatsAppTemplate.message_template_id.in_(central_template_ids)
            )
        )
    ).scalars().all()
    return {r.message_template_id: r for r in rows}


# --- campaign CRUD ------------------------------------------------------


async def count_all_campaigns(session: AsyncSession) -> int:
    """Total campaign rows (auto-tenant-filtered) for paging."""
    result = await session.execute(
        select(func.count()).select_from(Campaign)
    )
    return int(result.scalar_one())


async def list_campaigns_page(
    session: AsyncSession, *, offset: int, limit: int
) -> list[Campaign]:
    """Page of campaigns sorted newest-first."""
    rows = (
        await session.execute(
            select(Campaign)
            .order_by(Campaign.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


def add_campaign(session: AsyncSession, campaign: Campaign) -> Campaign:
    """Stage a new campaign in the unit-of-work."""
    session.add(campaign)
    return campaign


async def delete_campaign_row(
    session: AsyncSession, campaign: Campaign
) -> None:
    """Hard-delete a campaign row."""
    await session.delete(campaign)


# --- audience -----------------------------------------------------------


async def list_contact_ids_for_audience(
    session: AsyncSession,
    *,
    q: str | None,
    source: str | None,
    tag: str | None,
) -> list[uuid.UUID]:
    """Resolve the (q / source / tag) audience filter into contact ids.

    Empty filter ⇒ every contact in the org (auto-tenant-scoped).
    """
    filters: list[Any] = []
    if q:
        like = f"%{q}%"
        filters.append(
            or_(
                Contact.full_name.ilike(like),
                Contact.phone.ilike(like),
                Contact.email.ilike(like),
            )
        )
    if source:
        filters.append(Contact.source == source)
    if tag:
        filters.append(Contact.tags.contains([tag]))

    stmt = select(Contact.id)
    if filters:
        stmt = stmt.where(and_(*filters))
    return [row for (row,) in (await session.execute(stmt)).all()]


# --- per-message rows ---------------------------------------------------


async def bulk_upsert_queued_campaign_messages(
    session: AsyncSession,
    *,
    rows: list[dict[str, Any]],
) -> None:
    """Idempotent insert of placeholder `tbl_campaign_messages` rows.

    `ON CONFLICT DO NOTHING` on `(campaign_id, contact_id)` means a
    retried `start` won't duplicate rows for the same chunk.
    """
    if not rows:
        return
    await session.execute(
        pg_insert(CampaignMessage)
        .values(rows)
        .on_conflict_do_nothing(
            index_elements=["campaign_id", "contact_id"]
        )
    )


async def get_campaign_message_for_contact(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    contact_id: uuid.UUID,
) -> CampaignMessage | None:
    """Resolve the per-contact `CampaignMessage` row for one campaign."""
    result = await session.execute(
        select(CampaignMessage)
        .where(CampaignMessage.campaign_id == campaign_id)
        .where(CampaignMessage.contact_id == contact_id)
    )
    return result.scalar_one_or_none()


async def get_campaign_message_by_channel_id(
    session: AsyncSession, channel_message_id: str
) -> CampaignMessage | None:
    """Look up a `CampaignMessage` row by Meta's `channel_message_id`."""
    result = await session.execute(
        select(CampaignMessage).where(
            CampaignMessage.channel_message_id == channel_message_id
        )
    )
    return result.scalar_one_or_none()


async def get_campaign_message_in_campaign(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    message_id: uuid.UUID,
) -> CampaignMessage | None:
    """Verify a message belongs to a campaign (404 guard from the service)."""
    result = await session.execute(
        select(CampaignMessage)
        .where(CampaignMessage.id == message_id)
        .where(CampaignMessage.campaign_id == campaign_id)
    )
    return result.scalar_one_or_none()


async def count_queued_messages_for_campaign(
    session: AsyncSession, campaign_id: uuid.UUID
) -> int:
    """Number of `status='queued'` rows still pending for one campaign."""
    result = await session.execute(
        select(func.count())
        .select_from(CampaignMessage)
        .where(CampaignMessage.campaign_id == campaign_id)
        .where(CampaignMessage.status == CampaignMessageStatus.queued)
    )
    return int(result.scalar_one() or 0)


async def count_messages_filtered(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    status_filter: CampaignMessageStatus | None,
) -> int:
    """Per-status count of `CampaignMessage` rows in one campaign."""
    filters: list[Any] = [CampaignMessage.campaign_id == campaign_id]
    if status_filter is not None:
        filters.append(CampaignMessage.status == status_filter)
    result = await session.execute(
        select(func.count())
        .select_from(CampaignMessage)
        .where(and_(*filters))
    )
    return int(result.scalar_one())


async def list_messages_page(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    status_filter: CampaignMessageStatus | None,
    offset: int,
    limit: int,
) -> list[CampaignMessage]:
    """Page of `CampaignMessage` rows for the detail view."""
    filters: list[Any] = [CampaignMessage.campaign_id == campaign_id]
    if status_filter is not None:
        filters.append(CampaignMessage.status == status_filter)
    rows = (
        await session.execute(
            select(CampaignMessage)
            .where(and_(*filters))
            .order_by(CampaignMessage.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def stats_by_status(
    session: AsyncSession, *, campaign_id: uuid.UUID
) -> list[tuple[CampaignMessageStatus, int]]:
    """`(status, count)` rows for a campaign — fuels the stats endpoint."""
    rows = (
        await session.execute(
            select(CampaignMessage.status, func.count(CampaignMessage.id))
            .where(CampaignMessage.campaign_id == campaign_id)
            .group_by(CampaignMessage.status)
        )
    ).all()
    return [(r[0], int(r[1])) for r in rows]


# --- conversation + inbox message rows ----------------------------------
#
# Campaigns reach into `conversations` to append outbound messages so
# the inbox UI shows them alongside replies. This is the only place
# we cross module boundaries to write conversation rows; the helpers
# are co-located here rather than in `conversations.data_access`
# because dispatch owns the find-or-create semantics.


async def get_conversation_by_external_id(
    session: AsyncSession,
    *,
    channel: ConversationChannel,
    external_id: str,
) -> Conversation | None:
    """Resolve a conversation by `(channel, external_id)` pair."""
    result = await session.execute(
        select(Conversation)
        .where(Conversation.channel == channel)
        .where(Conversation.external_id == external_id)
    )
    return result.scalar_one_or_none()


def add_conversation(
    session: AsyncSession, conversation: Conversation
) -> Conversation:
    """Stage a new conversation row in the unit-of-work."""
    session.add(conversation)
    return conversation


def add_outbound_message(session: AsyncSession, message: Message) -> Message:
    """Stage an outbound `Message` row in the unit-of-work."""
    session.add(message)
    return message


__all__ = [
    "add_campaign",
    "add_outbound_message",
    "bulk_upsert_queued_campaign_messages",
    "count_all_campaigns",
    "count_messages_filtered",
    "count_queued_messages_for_campaign",
    "delete_campaign_row",
    "get_campaign_message_by_channel_id",
    "get_campaign_message_for_contact",
    "get_campaign_message_in_campaign",
    "get_conversation_by_external_id",
    "get_wa_extension_for_campaign_template",
    "get_wa_extensions_for_template_ids",
    "add_conversation",
    "list_campaigns_page",
    "list_contact_ids_for_audience",
    "list_messages_page",
    "stats_by_status",
]
