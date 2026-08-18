"""Data-access layer for the WhatsApp integration module.

Pure query helpers — no transactions, no audit. Leaf module; never
imports a `service.py`.

Three lookups against ``tbl_whatsapp_templates``: by own PK, by central
template UUID (Step-9 reverse-lookup so a central template finds its
Meta-specific extension row), and by Meta's template id (Step-8
webhook routing for ``status_update`` events).

Tenant scoping comes from the global ``do_orm_execute`` listener
(WhatsAppTemplate is TenantScoped); callers must have
``RequestContext.org_id`` set.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.integrations.whatsapp.models import WhatsAppTemplate


async def get_by_id(session: AsyncSession, template_id: uuid.UUID) -> WhatsAppTemplate | None:
    """Resolve a WA template by its own UUID PK."""
    result = await session.execute(
        select(WhatsAppTemplate).where(WhatsAppTemplate.id == template_id)
    )
    return result.scalar_one_or_none()


async def get_by_message_template_id(
    session: AsyncSession, message_template_id: uuid.UUID
) -> WhatsAppTemplate | None:
    """Reverse lookup — given the central row's UUID, return the
    WA extension row (if any). Used by the Step-9 external-submission
    dispatcher when the central row was created via the new editor and
    needs its Meta-specific sidecar."""
    result = await session.execute(
        select(WhatsAppTemplate).where(WhatsAppTemplate.message_template_id == message_template_id)
    )
    return result.scalar_one_or_none()


async def get_by_meta_template_id(
    session: AsyncSession, meta_template_id: str
) -> WhatsAppTemplate | None:
    """Webhook reverse lookup — given Meta's template id, return the
    WA extension row. ``status_update`` webhooks (Step 8 of
    ``whatsapp-platform-upgrade``) call into this to route the
    update."""
    result = await session.execute(
        select(WhatsAppTemplate).where(WhatsAppTemplate.meta_template_id == meta_template_id)
    )
    return result.scalar_one_or_none()


async def get_by_integration_name_lang(
    session: AsyncSession,
    *,
    integration_id: uuid.UUID,
    name: str,
    language: str,
) -> WhatsAppTemplate | None:
    """Lookup by the natural key that backs
    ``uq_whatsapp_templates_integration_name_lang``. Used by
    ``ensure_wa_extension_row`` to adopt an existing orphan row (Meta
    sync creates rows with ``message_template_id=NULL``) instead of
    tripping the unique constraint on an INSERT."""
    result = await session.execute(
        select(WhatsAppTemplate).where(
            WhatsAppTemplate.integration_id == integration_id,
            WhatsAppTemplate.name == name,
            WhatsAppTemplate.language == language,
        )
    )
    return result.scalar_one_or_none()


__all__ = [
    "get_by_id",
    "get_by_integration_name_lang",
    "get_by_message_template_id",
    "get_by_meta_template_id",
]
