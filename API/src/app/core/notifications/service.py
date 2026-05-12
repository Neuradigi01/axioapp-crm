"""Service layer for notifications.

Three public entry points:

- **`notify(user_id, type, title, ...)`** — non-raising helper any
  module imports to send a notification. Honours the recipient's
  `in_app` preference (skips writing if disabled); always pushes
  over WebSocket when the user has `in_app` enabled. Email and push
  channels are recognised by the preference schema but their delivery
  paths are deferred — `notify()` currently routes only to the in-app
  store + live socket fan-out.
- **`list_for_user` / `mark_read` / `mark_all_read`** — REST reads
  and writes the router exposes.
- **`get_preferences` / `update_preferences`** — per-user preference
  lookup + upsert. Missing rows default to enabled.

All DB calls run through the caller's `AsyncSession`; `notify()`
opens its own session so the call stays decoupled from the parent
request transaction (matches `audit.log` / `activities.log`).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.notifications.manager import manager
from src.app.core.notifications.models import (
    Notification,
    NotificationChannel,
    NotificationPreference,
)
from src.app.core.notifications.schemas import (
    NotificationOut,
    PreferenceUpdate,
)
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.db import async_session

logger = logging.getLogger(__name__)


async def notify(
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    type: str,
    title: str,
    body: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    """Persist a notification + push to active WebSocket connections.

    Never raises into the caller. Both the DB write and the broadcast
    are wrapped — a failure of either is logged and swallowed.

    The recipient's `in_app` preference is consulted: if explicitly
    disabled, the notification is skipped (no row, no broadcast).
    Missing preference rows default to enabled.
    """
    try:
        ctx_token = set_context(RequestContext(org_id=org_id, user_id=user_id))
        try:
            async with async_session() as session:
                if not await _channel_enabled(
                    session,
                    user_id=user_id,
                    type_=type,
                    channel=NotificationChannel.in_app,
                ):
                    return

                notification = Notification(
                    org_id=org_id,
                    user_id=user_id,
                    type=type,
                    title=title,
                    body=body,
                    payload=payload or {},
                )
                session.add(notification)
                await session.commit()
                await session.refresh(notification)

                wire = NotificationOut.model_validate(notification).model_dump(
                    mode="json"
                )
        finally:
            reset_context(ctx_token)

        # Broadcast outside the DB-session block so a slow socket
        # doesn't keep the connection checked out.
        try:
            await manager.broadcast(user_id, wire)
        except Exception:
            logger.exception(
                "notifications.broadcast failed user_id=%s type=%s", user_id, type
            )
    except Exception:
        logger.exception(
            "notifications.notify failed user_id=%s type=%s", user_id, type
        )


async def _channel_enabled(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    type_: str,
    channel: NotificationChannel,
) -> bool:
    """Default-enabled: if no preference row exists, the channel is on."""
    result = await session.execute(
        select(NotificationPreference.enabled)
        .where(NotificationPreference.user_id == user_id)
        .where(NotificationPreference.type == type_)
        .where(NotificationPreference.channel == channel)
    )
    row = result.scalar_one_or_none()
    return True if row is None else row


async def list_for_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    unread: Optional[bool] = None,
    limit: int = 50,
) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread is True:
        stmt = stmt.where(Notification.read_at.is_(None))
    elif unread is False:
        stmt = stmt.where(Notification.read_at.is_not(None))
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(
        limit
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def mark_read(
    session: AsyncSession, *, user_id: uuid.UUID, notification_id: uuid.UUID
) -> Optional[Notification]:
    """Mark a notification read. Returns the updated row or None if it
    doesn't exist / belongs to another user (we don't leak existence)."""
    result = await session.execute(
        select(Notification)
        .where(Notification.id == notification_id)
        .where(Notification.user_id == user_id)
    )
    notification = result.scalar_one_or_none()
    if notification is None:
        return None
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(notification)
    return notification


async def mark_all_read(
    session: AsyncSession, *, user_id: uuid.UUID
) -> int:
    """Mark every unread notification of the user as read. Returns count."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(Notification)
        .where(Notification.user_id == user_id)
        .where(Notification.read_at.is_(None))
        .values(read_at=now)
    )
    await session.commit()
    return int(result.rowcount or 0)


# --- Preferences ---


async def get_preferences(
    session: AsyncSession, *, user_id: uuid.UUID
) -> list[NotificationPreference]:
    """Return every explicit preference row this user has set.

    The frontend treats absent (type, channel) pairs as enabled, so the
    server doesn't pad the response with implicit `true` rows.
    """
    result = await session.execute(
        select(NotificationPreference)
        .where(NotificationPreference.user_id == user_id)
        .order_by(NotificationPreference.type, NotificationPreference.channel)
    )
    return list(result.scalars().all())


async def update_preferences(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    type_: str,
    payload: PreferenceUpdate,
) -> list[NotificationPreference]:
    """Upsert per-channel preferences for one notification type.

    Channels omitted from `payload` are left untouched. Returns all of
    this user's preference rows for the given `type` after the upsert.
    """
    channel_values: dict[NotificationChannel, bool] = {}
    if payload.in_app is not None:
        channel_values[NotificationChannel.in_app] = payload.in_app
    if payload.email is not None:
        channel_values[NotificationChannel.email] = payload.email
    if payload.push is not None:
        channel_values[NotificationChannel.push] = payload.push

    for channel, enabled in channel_values.items():
        stmt = (
            pg_insert(NotificationPreference)
            .values(
                org_id=org_id,
                user_id=user_id,
                type=type_,
                channel=channel,
                enabled=enabled,
            )
            .on_conflict_do_update(
                constraint="uq_notification_pref_user_type_channel",
                set_={"enabled": enabled, "updated_at": datetime.now(timezone.utc)},
            )
        )
        await session.execute(stmt)
    if channel_values:
        await session.commit()

    result = await session.execute(
        select(NotificationPreference)
        .where(NotificationPreference.user_id == user_id)
        .where(NotificationPreference.type == type_)
        .order_by(NotificationPreference.channel)
    )
    return list(result.scalars().all())


__all__ = [
    "NotificationChannel",
    "get_preferences",
    "list_for_user",
    "mark_all_read",
    "mark_read",
    "notify",
    "update_preferences",
]
