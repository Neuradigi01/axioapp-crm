"""Version-history lookups against ``tbl_message_template_versions``.

Pure reads, no commits. The service layer combines these with the
parent-template existence check (so a caller can't fish for versions
of a template that belongs to another org).
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.templates.models import MessageTemplateVersion


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
