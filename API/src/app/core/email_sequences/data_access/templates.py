"""Post-Step-10 template validation for email-sequence steps.

The sequence builder accepts a list of ``template_id`` values
(one per step). Each must:

  * point at a row in ``tbl_message_templates`` (post-migration the
    FK lives there);
  * carry ``channel='email'`` (sequences are email-only at v1);
  * be live (not archived).

This helper returns the subset of supplied ids that satisfy the
above. Sequence service compares the result against the input to
raise a clear 400 listing the offending ids.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates.models import (
    MessageTemplate,
    TemplateInternalStatus,
)


async def list_valid_email_template_ids(
    session: AsyncSession, template_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Return the subset of ``template_ids`` that point at live
    email templates in the current org. Tenant scoping is applied by
    the ``do_orm_execute`` listener."""
    if not template_ids:
        return set()
    rows = (
        await session.execute(
            select(MessageTemplate.id).where(
                MessageTemplate.id.in_(set(template_ids)),
                MessageTemplate.channel == ConversationChannel.email,
                MessageTemplate.internal_status != TemplateInternalStatus.archived,
            )
        )
    ).all()
    return {r.id for r in rows}
