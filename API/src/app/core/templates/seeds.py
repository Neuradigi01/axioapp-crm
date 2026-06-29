"""Idempotent template seeders installed at org-creation time.

Step 5 of ``tasks/automation-engine/`` seeds a default "User
Welcome" email template into every new org so the
:data:`user.signed_up` event has something to render at the
moment the Owner finishes signup. Future steps add more seeded
templates (Lead Confirmation in Step 6 of the same track).

Seeds are inserted as **published** templates so the automation
dispatcher can use them without an internal-review cycle.
Operators can edit / rename / archive them via the regular
templates editor (`/user/templates`) — the seeders are idempotent
on ``(org_id, lower(name), channel)`` so re-running them never
overwrites operator changes.

Cross-track dependency: this module is imported by
:mod:`core.tenants.service.create_organization` (the canonical
new-org chokepoint) so the seeded rows land inside the same
transaction as the org row itself. A signup that rolls back also
rolls back the seeds. Backfill migration
``0129_seed_user_welcome_existing_orgs`` runs the same seeders
against every pre-existing org.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates.models import (
    MessageTemplate,
    MessageTemplateVersion,
    TemplateCategory,
    TemplateExternalStatus,
    TemplateInternalStatus,
)


logger = logging.getLogger(__name__)


_USER_WELCOME_NAME = "User Welcome"
_USER_WELCOME_SUBJECT = "Welcome to {{ org.name }}"
_USER_WELCOME_BODY = (
    "Hi {{ user.full_name }},\n\n"
    "Welcome to {{ org.name }}! Your workspace is ready — sign in any "
    "time to start adding contacts, building campaigns, and inviting "
    "your team.\n\n"
    "If you have any questions, just reply to this email.\n\n"
    "— The {{ org.name }} team"
)


async def seed_user_welcome_template(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> MessageTemplate:
    """Insert (or return the existing) "User Welcome" email template
    for ``org_id``. Caller owns the transaction — does not commit.

    Idempotent: a second call returns the prior row unchanged, so
    operators who renamed the template won't get a duplicate at the
    next backfill run.
    """
    existing = (
        await session.execute(
            select(MessageTemplate).where(
                MessageTemplate.org_id == org_id,
                func.lower(MessageTemplate.name) == _USER_WELCOME_NAME.lower(),
                MessageTemplate.channel == ConversationChannel.email,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    template = MessageTemplate(
        org_id=org_id,
        channel=ConversationChannel.email,
        name=_USER_WELCOME_NAME,
        category=TemplateCategory.transactional,
        language="en",
        body_text=_USER_WELCOME_BODY,
        subject=_USER_WELCOME_SUBJECT,
        # Variables the renderer should resolve at send time. Kept in
        # sync with the body string above + the event_catalog payload
        # for `user.signed_up`.
        variables=["user.full_name", "org.name"],
        internal_status=TemplateInternalStatus.published,
        external_status=TemplateExternalStatus.n_a,
        current_version=1,
    )
    session.add(template)
    await session.flush()

    version = MessageTemplateVersion(
        org_id=org_id,
        template_id=template.id,
        version=1,
        body_text=template.body_text,
        subject=template.subject,
        variables=template.variables,
        change_note="seeded by automation-engine Step 5 (User Welcome)",
    )
    session.add(version)
    await session.flush()

    logger.info(
        "templates.seed user_welcome org=%s template=%s",
        org_id,
        template.id,
    )
    return template


__all__ = ["seed_user_welcome_template"]
