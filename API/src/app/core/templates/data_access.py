"""Data-access layer for the central template library.

Pure query helpers — no transactions, no audit, no commits. Leaf
module; never imports a ``service.py``.

Three concerns, kept in one file per the project's layered-architecture
spec (manager-locked 2026-06-25):

  * ``tbl_message_templates``     — lookups + filterable list
  * ``tbl_message_template_versions`` — version-history lookups
  * ``tbl_sms_dlt_templates``     — SMS-DLT extension lookups
    (companion writes live in :mod:`core.templates.sms_extension`)

Tenant scoping is applied automatically by the ``do_orm_execute``
listener on every SELECT, but we also pass ``org_id`` explicitly in
the WHERE clause as a belt to the suspenders — defends callers that
forget to set ``RequestContext.org_id`` (Celery tasks, scripts).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.models import ConversationChannel
from src.app.core.integrations.whatsapp.models import WhatsAppTemplate
from src.app.core.templates.models import (
    MessageTemplate,
    MessageTemplateReview,
    MessageTemplateVersion,
    TemplateExternalStatus,
    TemplateInternalStatus,
)
from src.app.core.templates.sms_extension import SMSDLTTemplate

# --- tbl_message_templates ----------------------------------------------


async def get_by_external_provider_id(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    external_provider_id: str,
) -> MessageTemplate | None:
    """Reverse lookup — given the provider's template id (Meta /
    SMS-DLT), return the central row in this org. Used by the Step-14
    status-sync path + the Meta webhook handler to update the central
    row's ``external_status`` when Meta fires a status_update event."""
    result = await session.execute(
        select(MessageTemplate).where(
            MessageTemplate.org_id == org_id,
            MessageTemplate.external_provider_id == external_provider_id,
        )
    )
    return result.scalar_one_or_none()


async def get_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> MessageTemplate | None:
    """Resolve a template by its UUID PK. ``None`` if missing or
    cross-tenant (callers translate to :class:`TemplateNotFound`)."""
    result = await session.execute(
        select(MessageTemplate).where(
            MessageTemplate.id == template_id,
            MessageTemplate.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def list_pending_external(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> list[MessageTemplate]:
    """Every template whose ``external_status`` is still in flux
    (``pending`` or ``paused``) for this org. Used by the Step-14
    hourly Celery sweep to know which rows to re-check against Meta.

    ``rejected`` is NOT included on purpose — once Meta rejects the
    operator must Resubmit to move it forward; the sweep would just
    poll a frozen value otherwise. ``approved`` rows are also stable
    until Meta proactively pauses or disables them, which arrives via
    the webhook path."""
    result = await session.execute(
        select(MessageTemplate).where(
            MessageTemplate.org_id == org_id,
            MessageTemplate.external_status.in_(
                (
                    TemplateExternalStatus.pending,
                    TemplateExternalStatus.paused,
                )
            ),
        )
    )
    return list(result.scalars().all())


async def list_templates(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    channel: ConversationChannel | None = None,
    internal_status: TemplateInternalStatus | None = None,
    external_status: TemplateExternalStatus | None = None,
    is_active: bool | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[MessageTemplate, str | None]], int]:
    """Filterable + paginated list. ``q`` matches against ``name`` or
    ``body_text`` (case-insensitive). ``is_active`` filters on the
    activation toggle — pickers pass ``True`` so operators never see
    an inactive template; the library page passes ``None`` so admins
    can review everything. Returns ``(rows, total)`` where each row
    is ``(MessageTemplate, external_rejection_reason)`` — the reason
    is a LEFT OUTER JOIN onto the WhatsApp extension so Meta-rejected
    rows carry their reason without an N+1 fetch. Non-WA rows always
    come back with reason=None."""
    base = select(MessageTemplate).where(MessageTemplate.org_id == org_id)

    if channel is not None:
        base = base.where(MessageTemplate.channel == channel)
    else:
        # `ai_prompt` is an internal channel used exclusively by the
        # AI Assistants editor's "Preset" dropdown — the rows are
        # starter prompts, not sends. Excluding them from the default
        # list keeps the org's Templates library scoped to real
        # customer-facing templates (WhatsApp / Email / SMS / Web).
        # Callers that need them (the AI editor) pass
        # ``channel=ai_prompt`` explicitly and the branch above kicks
        # in.
        base = base.where(MessageTemplate.channel != ConversationChannel.ai_prompt)
    if internal_status is not None:
        base = base.where(MessageTemplate.internal_status == internal_status)
    if external_status is not None:
        base = base.where(MessageTemplate.external_status == external_status)
    if is_active is not None:
        base = base.where(MessageTemplate.is_active.is_(is_active))
    if q:
        pattern = f"%{q.lower()}%"
        base = base.where(
            or_(
                func.lower(MessageTemplate.name).like(pattern),
                func.lower(MessageTemplate.body_text).like(pattern),
            )
        )

    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

    # Attach the WhatsApp extension's rejection_reason via LEFT OUTER JOIN.
    # message_template_id is the reciprocal FK back to tbl_message_templates,
    # one-to-one for WA rows and NULL for every other channel.
    listing = (
        select(MessageTemplate, WhatsAppTemplate.rejection_reason)
        .outerjoin(
            WhatsAppTemplate,
            WhatsAppTemplate.message_template_id == MessageTemplate.id,
        )
        .where(MessageTemplate.org_id == org_id)
    )
    if channel is not None:
        listing = listing.where(MessageTemplate.channel == channel)
    else:
        # Mirror the count-query exclusion above so listing + total
        # stay in lockstep (otherwise `total` and `len(items)` diverge
        # on a page where `ai_prompt` rows would have appeared).
        listing = listing.where(MessageTemplate.channel != ConversationChannel.ai_prompt)
    if internal_status is not None:
        listing = listing.where(MessageTemplate.internal_status == internal_status)
    if external_status is not None:
        listing = listing.where(MessageTemplate.external_status == external_status)
    if is_active is not None:
        listing = listing.where(MessageTemplate.is_active.is_(is_active))
    if q:
        pattern = f"%{q.lower()}%"
        listing = listing.where(
            or_(
                func.lower(MessageTemplate.name).like(pattern),
                func.lower(MessageTemplate.body_text).like(pattern),
            )
        )

    result = await session.execute(
        listing.order_by(MessageTemplate.updated_at.desc()).offset(offset).limit(limit)
    )
    rows: list[tuple[MessageTemplate, str | None]] = [
        (row[0], row[1]) for row in result.all()
    ]
    return rows, int(total)


async def latest_reviews_for_templates(
    session: AsyncSession,
    template_ids: list[uuid.UUID],
) -> dict[uuid.UUID, tuple[uuid.UUID | None, str, datetime]]:
    """Return ``{template_id: (reviewer_user_id, action, created_at)}``
    for every template in ``template_ids`` that has at least one review
    row. Latest = most recent ``created_at``.

    Powers the list / detail endpoints' ``last_reviewed_*`` fields so
    the SPA can render "Approved by X on Y" without an N+1 fetch per
    row. Templates with no review history are simply absent from the
    returned dict — the caller sets the three fields to ``None`` in
    that case."""
    if not template_ids:
        return {}
    # Window-function pick: rank rows per template_id by created_at DESC,
    # take rank=1. Single scan of the audit table with an index-supported
    # partition instead of N per-template ORDER BY LIMIT 1 subqueries.
    ranked = (
        select(
            MessageTemplateReview.template_id,
            MessageTemplateReview.reviewer_user_id,
            MessageTemplateReview.action,
            MessageTemplateReview.created_at,
            func.row_number()
            .over(
                partition_by=MessageTemplateReview.template_id,
                order_by=MessageTemplateReview.created_at.desc(),
            )
            .label("rn"),
        )
        .where(MessageTemplateReview.template_id.in_(template_ids))
        .subquery()
    )
    result = await session.execute(
        select(
            ranked.c.template_id,
            ranked.c.reviewer_user_id,
            ranked.c.action,
            ranked.c.created_at,
        ).where(ranked.c.rn == 1)
    )
    out: dict[uuid.UUID, tuple[uuid.UUID | None, str, datetime]] = {}
    for tpl_id, reviewer_id, action, created_at in result.all():
        # ``action`` comes back as the enum instance — .value for the
        # string wire representation the schema expects.
        out[tpl_id] = (reviewer_id, action.value, created_at)
    return out


# --- tbl_message_template_versions --------------------------------------


async def list_versions(
    session: AsyncSession,
    *,
    template_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[MessageTemplateVersion]:
    """All versions of ``template_id``, newest first."""
    rows = (
        (
            await session.execute(
                select(MessageTemplateVersion)
                .where(MessageTemplateVersion.template_id == template_id)
                .order_by(MessageTemplateVersion.version.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def get_version(
    session: AsyncSession,
    *,
    template_id: uuid.UUID,
    version: int,
) -> MessageTemplateVersion | None:
    """One specific past version. ``None`` if absent — the service
    raises :class:`TemplateNotFound` (no separate exception so clients
    can't distinguish "template missing" from "version missing")."""
    result = await session.execute(
        select(MessageTemplateVersion).where(
            MessageTemplateVersion.template_id == template_id,
            MessageTemplateVersion.version == version,
        )
    )
    return result.scalar_one_or_none()


# --- tbl_sms_dlt_templates ----------------------------------------------


async def get_dlt_metadata(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> SMSDLTTemplate | None:
    """Resolve the DLT extension row keyed on the central template
    id. ``None`` when the SMS template has never had DLT metadata
    captured (fresh draft)."""
    result = await session.execute(
        select(SMSDLTTemplate).where(
            SMSDLTTemplate.message_template_id == template_id,
            SMSDLTTemplate.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def find_by_dlt_template_id(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    dlt_template_id: str,
) -> SMSDLTTemplate | None:
    """Reverse lookup by the TRAI-issued template id. Used by future
    DLT status-sync paths to route an external status update to the
    matching central row."""
    result = await session.execute(
        select(SMSDLTTemplate).where(
            SMSDLTTemplate.org_id == org_id,
            SMSDLTTemplate.dlt_template_id == dlt_template_id,
        )
    )
    return result.scalar_one_or_none()


def add_template(session: AsyncSession, template: MessageTemplate) -> MessageTemplate:
    """Stage a new `tbl_message_templates` row in the unit-of-work."""
    session.add(template)
    return template


def add_template_version(
    session: AsyncSession, version: MessageTemplateVersion
) -> MessageTemplateVersion:
    """Stage a new `tbl_message_template_versions` row in the unit-of-work."""
    session.add(version)
    return version


__all__ = [
    "add_template",
    "add_template_version",
    "find_by_dlt_template_id",
    "get_by_external_provider_id",
    "get_dlt_metadata",
    "get_template",
    "get_version",
    "list_pending_external",
    "list_templates",
    "list_versions",
]
