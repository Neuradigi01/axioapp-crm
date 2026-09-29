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

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.campaigns.models import (
    Campaign,
    CampaignMessage,
    CampaignMessageStatus,
    CampaignStatus,
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
        select(WhatsAppTemplate)
        .where(WhatsAppTemplate.message_template_id == central_template_id)
        .order_by(WhatsAppTemplate.updated_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def get_wa_extensions_for_template_ids(
    session: AsyncSession, central_template_ids: list[uuid.UUID]
) -> dict[uuid.UUID, WhatsAppTemplate]:
    """Bulk-lookup WhatsApp extension rows keyed by central template id."""
    if not central_template_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(WhatsAppTemplate).where(
                    WhatsAppTemplate.message_template_id.in_(central_template_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    return {r.message_template_id: r for r in rows}


# --- campaign CRUD ------------------------------------------------------


async def count_all_campaigns(session: AsyncSession) -> int:
    """Total campaign rows (auto-tenant-filtered) for paging."""
    result = await session.execute(select(func.count()).select_from(Campaign))
    return int(result.scalar_one())


async def count_campaigns_by_status_for_smtp_sender(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    smtp_sender_id: uuid.UUID,
    include_archived: bool = False,
) -> dict[str, int]:
    """Group campaigns that reference this SMTP sender by status.

    Used by the email-senders delete-sender flow to produce a helpful
    409 message instead of letting the FK RESTRICT violation surface
    as a raw asyncpg IntegrityError / 500.

    Archived campaigns (``archived_at IS NOT NULL``) are excluded by
    default — an operator who archived their historical Sent
    campaigns before trying to remove the sender expects "no
    references" and shouldn't be blocked by rows they've deliberately
    put out of view.
    """
    stmt = select(Campaign.status, func.count()).where(
        Campaign.org_id == org_id,
        Campaign.smtp_sender_id == smtp_sender_id,
    )
    if not include_archived:
        stmt = stmt.where(Campaign.archived_at.is_(None))
    result = await session.execute(stmt.group_by(Campaign.status))
    return {
        str(status.value if hasattr(status, "value") else status): int(n)
        for status, n in result.all()
    }


async def list_campaigns_page(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    include_archived: bool = False,
    archived_only: bool = False,
) -> list[Campaign]:
    """Page of campaigns sorted newest-first.

    ``include_archived`` widens the result to include soft-archived
    rows; ``archived_only`` narrows to ONLY archived rows (for the
    "Archived" filter chip on the frontend). Passing both is a
    caller bug — the archived-only branch wins.
    """
    stmt = select(Campaign)
    if archived_only:
        stmt = stmt.where(Campaign.archived_at.is_not(None))
    elif not include_archived:
        stmt = stmt.where(Campaign.archived_at.is_(None))
    rows = (
        (
            await session.execute(
                stmt.order_by(Campaign.created_at.desc()).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


def add_campaign(session: AsyncSession, campaign: Campaign) -> Campaign:
    """Stage a new campaign in the unit-of-work."""
    session.add(campaign)
    return campaign


async def delete_campaign_row(session: AsyncSession, campaign: Campaign) -> None:
    """Hard-delete a campaign row."""
    await session.delete(campaign)


async def archive_campaign_row(session: AsyncSession, campaign: Campaign, *, now: datetime) -> None:
    """Soft-archive: stamp ``archived_at`` with ``now``. Idempotent —
    re-archiving an already-archived row is a no-op at this layer
    (service enforces the transition validity)."""
    campaign.archived_at = now


async def unarchive_campaign_row(session: AsyncSession, campaign: Campaign) -> None:
    """Restore an archived row to the default list."""
    campaign.archived_at = None


# --- audience -----------------------------------------------------------


async def list_contact_ids_in_scope(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
) -> list[uuid.UUID]:
    """Return the subset of `ids` that exist in the caller's tenant.

    The ORM filter drops any row from another org automatically, so
    passing a stray id from an outside tenant silently produces an
    empty match rather than leaking data. Deleted-since-save ids also
    fall out here.
    """
    if not ids:
        return []
    stmt = select(Contact.id).where(Contact.id.in_(ids))
    return [row for (row,) in (await session.execute(stmt)).all()]


async def list_contact_ids_for_audience(
    session: AsyncSession,
    *,
    q: str | None,
    source: str | None,
    tag: str | None,
    lead_statuses: list[str] | None = None,
    lead_stages: list[str] | None = None,
    lead_sources: list[str] | None = None,
    lead_form_ids: list[uuid.UUID] | None = None,
) -> list[uuid.UUID]:
    """Resolve the audience filter into contact ids.

    Contact-level predicates (``q`` / ``source`` / ``tag``) still match
    columns on `tbl_contacts` directly. The lead-linked predicates
    (``lead_statuses`` / ``lead_stages`` / ``lead_sources``) each emit
    an EXISTS subquery against `tbl_leads` — a contact qualifies when
    it has at least one lead matching every requested facet.

    Empty filter ⇒ every contact in the org (auto-tenant-scoped).
    """
    # Local import — Lead already depends on Contact via FK, so
    # importing at module scope would create a circular in the
    # campaigns → contacts → leads chain during model registration.
    from src.app.core.leads.models import Lead

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
    if lead_statuses:
        filters.append(
            select(Lead.id)
            .where(Lead.contact_id == Contact.id)
            .where(Lead.status.in_(lead_statuses))
            .exists()
        )
    if lead_stages:
        filters.append(
            select(Lead.id)
            .where(Lead.contact_id == Contact.id)
            .where(Lead.pipeline_stage.in_(lead_stages))
            .exists()
        )
    if lead_sources:
        filters.append(
            select(Lead.id)
            .where(Lead.contact_id == Contact.id)
            .where(Lead.source.in_(lead_sources))
            .exists()
        )
    if lead_form_ids:
        # Multi-form (Step 7): narrow "Forms" audience to specific
        # forms via ``attribution.form_id``. Same predicate the
        # contacts DAL uses — kept parallel so preview + dispatch
        # always agree.
        form_id_strings = [str(fid) for fid in lead_form_ids]
        filters.append(
            select(Lead.id)
            .where(Lead.contact_id == Contact.id)
            .where(Lead.source == "widget")
            .where(Lead.attribution["form_id"].astext.in_(form_id_strings))
            .exists()
        )

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
        .on_conflict_do_nothing(index_elements=["campaign_id", "contact_id"])
    )


async def get_campaign_message_for_contact(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    contact_id: uuid.UUID,
) -> CampaignMessage | None:
    """Resolve the per-contact `CampaignMessage` row for one campaign.
    Always re-reads the row so a status another worker wrote is seen."""
    result = await session.execute(
        select(CampaignMessage)
        .where(CampaignMessage.campaign_id == campaign_id)
        .where(CampaignMessage.contact_id == contact_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def get_campaign_message_by_channel_id(
    session: AsyncSession, channel_message_id: str
) -> CampaignMessage | None:
    """Look up a `CampaignMessage` row by Meta's `channel_message_id`."""
    result = await session.execute(
        select(CampaignMessage).where(CampaignMessage.channel_message_id == channel_message_id)
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


async def list_queued_contact_ids(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    contact_ids: list[uuid.UUID] | None = None,
) -> list[uuid.UUID]:
    """Contact ids whose row is still `queued` for one campaign,
    optionally narrowed to ``contact_ids``. Dispatch sends only to these
    so a retried / duplicated chunk never re-sends a finished row."""
    stmt = (
        select(CampaignMessage.contact_id)
        .where(CampaignMessage.campaign_id == campaign_id)
        .where(CampaignMessage.status == CampaignMessageStatus.queued)
        .order_by(CampaignMessage.created_at.asc())
    )
    if contact_ids is not None:
        if not contact_ids:
            return []
        stmt = stmt.where(CampaignMessage.contact_id.in_(contact_ids))
    return list((await session.execute(stmt)).scalars().all())


async def requeue_failed_messages(session: AsyncSession, *, campaign_id: uuid.UUID) -> None:
    """Flip every `failed` row of a campaign back to `queued` (restart
    of a failed campaign)."""
    await session.execute(
        update(CampaignMessage)
        .where(CampaignMessage.campaign_id == campaign_id)
        .where(CampaignMessage.status == CampaignMessageStatus.failed)
        .values(status=CampaignMessageStatus.queued, error=None)
    )


async def get_campaign_for_update(session: AsyncSession, campaign_id: uuid.UUID) -> Campaign | None:
    """Row-lock one campaign so concurrent starts serialise."""
    result = await session.execute(
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def fail_queued_messages(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    contact_ids: list[uuid.UUID],
    error: str,
) -> None:
    """Mark the given contacts' still-`queued` rows as `failed`."""
    if not contact_ids:
        return
    await session.execute(
        update(CampaignMessage)
        .where(CampaignMessage.campaign_id == campaign_id)
        .where(CampaignMessage.contact_id.in_(contact_ids))
        .where(CampaignMessage.status == CampaignMessageStatus.queued)
        .values(status=CampaignMessageStatus.failed, error=error)
    )


async def claim_scheduled_campaign(
    session: AsyncSession, *, campaign_id: uuid.UUID, now: datetime
) -> bool:
    """Atomically flip a due `scheduled` campaign to `running`. Returns
    False when another sweep already claimed it."""
    result = await session.execute(
        update(Campaign)
        .where(Campaign.id == campaign_id)
        .where(Campaign.status == CampaignStatus.scheduled)
        .where(Campaign.schedule_at <= now)
        .values(status=CampaignStatus.running)
        .returning(Campaign.id)
    )
    return result.scalar_one_or_none() is not None


async def list_due_scheduled_campaigns(
    session: AsyncSession, *, now: datetime, limit: int
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Cross-org `(id, org_id)` of scheduled campaigns whose time has come."""
    rows = await session.execute(
        select(Campaign.id, Campaign.org_id)
        .where(Campaign.status == CampaignStatus.scheduled)
        .where(Campaign.schedule_at.is_not(None))
        .where(Campaign.schedule_at <= now)
        .order_by(Campaign.schedule_at.asc())
        .limit(limit)
    )
    return [(r[0], r[1]) for r in rows.all()]


async def list_stalled_running_campaigns(
    session: AsyncSession, *, cutoff: datetime, limit: int
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Cross-org `(id, org_id)` of `running` campaigns that still have
    `queued` rows but no send progress since ``cutoff`` — their chunk
    task was lost (worker restart, broker outage, hard time limit)."""
    queued = func.count().filter(CampaignMessage.status == CampaignMessageStatus.queued)
    last_progress = func.coalesce(
        func.max(CampaignMessage.sent_at), func.min(CampaignMessage.created_at)
    )
    rows = await session.execute(
        select(Campaign.id, Campaign.org_id)
        .join(CampaignMessage, CampaignMessage.campaign_id == Campaign.id)
        .where(Campaign.status == CampaignStatus.running)
        .group_by(Campaign.id, Campaign.org_id)
        .having(queued > 0)
        .having(last_progress < cutoff)
        .limit(limit)
    )
    return [(r[0], r[1]) for r in rows.all()]


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
        select(func.count()).select_from(CampaignMessage).where(and_(*filters))
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
        (
            await session.execute(
                select(CampaignMessage)
                .where(and_(*filters))
                .order_by(CampaignMessage.created_at.asc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
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


async def email_tracking_counts(session: AsyncSession, *, campaign_id: uuid.UUID) -> dict[str, int]:
    """Campaigns v1 Step 05 — per-classifier counts for the Email
    funnel. ``bounced`` counts rows with a non-null ``bounced_at``,
    ``unsubscribed`` counts rows with a non-null ``unsubscribed_at``.
    Both live in dedicated timestamp columns (migration 0153) rather
    than status-enum values so a single row can carry both flags
    (a contact might click, then bounce, then unsubscribe)."""
    bounced_count = (
        await session.execute(
            select(func.count(CampaignMessage.id)).where(
                CampaignMessage.campaign_id == campaign_id,
                CampaignMessage.bounced_at.is_not(None),
            )
        )
    ).scalar_one()
    unsub_count = (
        await session.execute(
            select(func.count(CampaignMessage.id)).where(
                CampaignMessage.campaign_id == campaign_id,
                CampaignMessage.unsubscribed_at.is_not(None),
            )
        )
    ).scalar_one()
    return {
        "bounced": int(bounced_count or 0),
        "unsubscribed": int(unsub_count or 0),
    }


async def dashboard_stats_since(session: AsyncSession, *, since: datetime) -> dict[str, int]:
    """Aggregate `CampaignMessage` counts across all campaigns whose
    messages were sent on or after `since`.

    Rolls up three top-level metrics for the Campaigns dashboard:
      - ``sent``      — rows with ``sent_at >= since``
      - ``delivered`` — subset of the above whose ``delivered_at`` is set
      - ``read``      — subset whose ``read_at`` (WhatsApp) or
                        ``opened_at`` (Email) is set

    The join to ``tbl_campaigns`` lets Postgres' RLS on the parent
    table scope the aggregate to the caller's org — CampaignMessage
    has no ``org_id`` of its own.
    """
    row = (
        await session.execute(
            select(
                func.count().filter(CampaignMessage.sent_at.is_not(None)).label("sent"),
                func.count().filter(CampaignMessage.delivered_at.is_not(None)).label("delivered"),
                func.count()
                .filter(
                    or_(
                        CampaignMessage.read_at.is_not(None),
                        CampaignMessage.opened_at.is_not(None),
                    )
                )
                .label("read"),
            )
            .select_from(CampaignMessage)
            .join(Campaign, Campaign.id == CampaignMessage.campaign_id)
            .where(CampaignMessage.sent_at >= since)
        )
    ).one()
    return {
        "sent": int(row.sent or 0),
        "delivered": int(row.delivered or 0),
        "read": int(row.read or 0),
    }


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
    org_id: uuid.UUID,
    channel: ConversationChannel,
    external_id: str,
) -> Conversation | None:
    """Resolve the org's most recent conversation for a
    `(channel, external_id)` pair."""
    result = await session.execute(
        select(Conversation)
        .where(Conversation.org_id == org_id)
        .where(Conversation.channel == channel)
        .where(Conversation.external_id == external_id)
        .order_by(Conversation.last_message_at.desc().nulls_last())
        .limit(1)
    )
    return result.scalars().first()


def add_conversation(session: AsyncSession, conversation: Conversation) -> Conversation:
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
    "count_campaigns_by_status_for_smtp_sender",
    "count_messages_filtered",
    "claim_scheduled_campaign",
    "delete_campaign_row",
    "fail_queued_messages",
    "get_campaign_for_update",
    "get_campaign_message_by_channel_id",
    "get_campaign_message_for_contact",
    "get_campaign_message_in_campaign",
    "get_conversation_by_external_id",
    "get_wa_extension_for_campaign_template",
    "get_wa_extensions_for_template_ids",
    "add_conversation",
    "list_campaigns_page",
    "list_contact_ids_for_audience",
    "list_due_scheduled_campaigns",
    "list_messages_page",
    "list_queued_contact_ids",
    "list_stalled_running_campaigns",
    "requeue_failed_messages",
    "stats_by_status",
    "email_tracking_counts",
    "dashboard_stats_since",
]
