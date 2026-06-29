"""Idempotent trigger seeders installed at org-creation time.

Step 5 of ``tasks/automation-engine/`` seeds a default "User
Welcome" trigger that fires on :data:`user.signed_up` and sends
the matching email template (see :mod:`core.templates.seeds`).
Step 6 will add a "Lead Confirmation" trigger that fires on
:data:`lead.created` from every source.

Seeds are inserted as **enabled** so the manager's "welcome mail
on signup" promise is live the moment Step 5 lands. Operators can
disable or edit them via the regular Settings → Automations
surface (Steps 7-9 wire the UI; the API is already live from
Step 3). Idempotent on ``(org_id, lower(name))`` — re-runs never
duplicate.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.automation import data_access
from src.app.core.automation.models import AutomationTrigger
from src.app.core.conversations.models import ConversationChannel


logger = logging.getLogger(__name__)


_USER_WELCOME_TRIGGER_NAME = "User Welcome"


async def seed_user_welcome_trigger(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
) -> AutomationTrigger:
    """Insert (or return the existing) "User Welcome" automation
    trigger for ``org_id``. Caller owns the transaction.

    Idempotent: a second call returns the prior row unchanged —
    safe to re-run from backfill migrations + org-create hooks
    without producing duplicates.
    """
    existing = await data_access.get_trigger_by_name(
        session, org_id=org_id, name=_USER_WELCOME_TRIGGER_NAME
    )
    if existing is not None:
        return existing

    trigger = AutomationTrigger(
        org_id=org_id,
        name=_USER_WELCOME_TRIGGER_NAME,
        enabled=True,
        event_type="user.signed_up",
        conditions={},
        channel=ConversationChannel.email,
        template_id=template_id,
        delay_seconds=0,
        recipient_resolver="user.email",
        recipient_resolver_config={},
        created_by_user_id=None,
        updated_by_user_id=None,
    )
    session.add(trigger)
    await session.flush()
    logger.info(
        "automation.seed user_welcome org=%s trigger=%s template=%s",
        org_id,
        trigger.id,
        template_id,
    )
    return trigger


async def install_default_org_seeds(
    session: AsyncSession, *, org_id: uuid.UUID
) -> dict:
    """Single entry-point called by ``core.tenants.service.create_organization``
    + the backfill migration. Wires the Welcome template + trigger.
    Future steps add more seeds here (Lead Confirmation in Step 6).

    Returns a small dict with the seeded ids — useful for the
    backfill migration's per-org log line."""
    from src.app.core.templates.seeds import seed_user_welcome_template

    template = await seed_user_welcome_template(session, org_id=org_id)
    trigger = await seed_user_welcome_trigger(
        session, org_id=org_id, template_id=template.id
    )
    return {
        "template_id": str(template.id),
        "trigger_id": str(trigger.id),
    }


__all__ = ["install_default_org_seeds", "seed_user_welcome_trigger"]
