"""Campaign-side template lookups.

Step 11 of ``tasks/template-library`` switched
``tbl_campaigns.template_id`` (and the A/B variants) from WA-template
UUIDs to central ``tbl_message_templates.id`` values. The dispatcher
still needs the Meta-specific extension row (header type, language,
button payloads) at send time — this DAL function resolves it via
the Step-9 reciprocal link.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.integrations.whatsapp.models import WhatsAppTemplate


async def get_wa_extension_for_campaign_template(
    session: AsyncSession, central_template_id: uuid.UUID
) -> WhatsAppTemplate | None:
    """Given the central row's UUID, return its WhatsApp extension
    row. ``None`` when the template isn't WA-channel (no extension)
    or when the link is missing (operator pre-Step-9 backfill or
    the extension was deleted)."""
    result = await session.execute(
        select(WhatsAppTemplate).where(
            WhatsAppTemplate.message_template_id == central_template_id
        )
    )
    return result.scalar_one_or_none()
