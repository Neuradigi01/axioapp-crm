"""SMS-DLT extension lookups against ``tbl_sms_dlt_templates``.

Pure queries. The companion writes (upsert + status flips) live in
:mod:`core.templates.sms_extension`.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.templates.sms_extension import SMSDLTTemplate


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
