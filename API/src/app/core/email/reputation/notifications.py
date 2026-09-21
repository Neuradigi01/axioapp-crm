"""Owner-notification helpers for the reputation-warmup track.

One entry: :func:`notify_owner`. Looks up the org's Owner (per the
locked role-templates spec — ``Role.name == 'Owner'`` AND
``Role.is_system is True``) and fires an in-app notification via the
shared notifications service. Best-effort — a missing Owner or
notifications outage never propagates into the evaluator (which
would abort a legitimate stage advance / shed on a downstream blip).

Mirrors ``core.email_sender_setup.tasks._notify_owner_of_transition``
line-for-line; kept here so the reputation module doesn't cross-
import into an unrelated track's task file.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def notify_owner(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    notification_type: str,
    title: str,
    body: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Send an in-app notification to the org's Owner. Never raises.

    Late imports so the reputation module doesn't drag the whole
    permissions + notifications stack into every cold-start.
    """
    try:
        from src.app.core.notifications.service import notify
        from src.app.core.permissions.models import Role
        from src.app.core.users.models import OrganizationMember, User

        owner_row = (
            await session.execute(
                select(User.legacy_uuid)
                .join(
                    OrganizationMember,
                    OrganizationMember.user_member_id == User.id,
                )
                .join(Role, Role.id == OrganizationMember.role_id)
                .where(OrganizationMember.organization_id == org_id)
                .where(OrganizationMember.is_active.is_(True))
                .where(Role.name == "Owner")
                .where(Role.is_system.is_(True))
                .limit(1)
            )
        ).scalar_one_or_none()
        if owner_row is None:
            logger.warning(
                "reputation.notify_owner: no active Owner for org=%s type=%s "
                "(notification skipped)",
                org_id,
                notification_type,
            )
            return
        await notify(
            org_id=org_id,
            user_id=owner_row,
            type=notification_type,
            title=title,
            body=body,
            payload=payload or {},
        )
    except Exception:
        logger.exception(
            "reputation.notify_owner: failed org=%s type=%s",
            org_id,
            notification_type,
        )


__all__ = ["notify_owner"]
