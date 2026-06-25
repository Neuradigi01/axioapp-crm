"""Template-table lookups against ``tbl_message_templates``.

Tenant scoping is applied automatically by the ``do_orm_execute``
listener on every SELECT, but we also pass ``org_id`` explicitly in
the WHERE clause as a belt to the suspenders — defends callers that
forget to set ``RequestContext.org_id`` (Celery tasks, scripts).
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates.models import (
    MessageTemplate,
    TemplateExternalStatus,
    TemplateInternalStatus,
)


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


async def list_templates(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    channel: ConversationChannel | None = None,
    internal_status: TemplateInternalStatus | None = None,
    external_status: TemplateExternalStatus | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MessageTemplate], int]:
    """Filterable + paginated list. ``q`` matches against ``name`` or
    ``body_text`` (case-insensitive). Returns ``(rows, total)``."""
    base = select(MessageTemplate).where(MessageTemplate.org_id == org_id)

    if channel is not None:
        base = base.where(MessageTemplate.channel == channel)
    if internal_status is not None:
        base = base.where(MessageTemplate.internal_status == internal_status)
    if external_status is not None:
        base = base.where(MessageTemplate.external_status == external_status)
    if q:
        pattern = f"%{q.lower()}%"
        base = base.where(
            or_(
                func.lower(MessageTemplate.name).like(pattern),
                func.lower(MessageTemplate.body_text).like(pattern),
            )
        )

    total = (
        await session.execute(
            select(func.count()).select_from(base.subquery())
        )
    ).scalar_one()

    rows = (
        (
            await session.execute(
                base.order_by(MessageTemplate.updated_at.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)
