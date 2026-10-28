"""Data-access layer for the notifications module.

Pure query helpers — no transactions, no audit, no broadcasts. Leaf
module; never imports a ``service.py``.

Two entity groups:

  * Notifications (``tbl_notifications``)
      get_notification_for_user, list_notifications_for_user,
      mark_all_unread_read, insert_notification
  * Preferences (``tbl_notification_preferences``)
      get_preference_enabled, list_preferences_for_user,
      upsert_preference (uses PostgreSQL
      ``INSERT ... ON CONFLICT DO UPDATE`` to keep concurrent
      preference writes safe)

Plus one cross-module helper:

  * lookup_user_email_by_legacy_uuid — User ⋈ UserInfo for the email
    fan-out path. The projection (single string) is notifications-
    specific so it lives here rather than in users/data_access.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.notifications.models import (
    Notification,
    NotificationChannel,
    NotificationPreference,
)
from src.app.core.users.models import User, UserInfo

# --- Notifications ------------------------------------------------------


async def get_notification_for_user(
    session: AsyncSession,
    *,
    notification_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Notification | None:
    """Single-row read scoped to one user — prevents leaking the
    existence of another user's notification on a guessed id."""
    result = await session.execute(
        select(Notification)
        .where(Notification.id == notification_id)
        .where(Notification.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_notifications_for_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    unread: bool | None = None,
    limit: int = 50,
) -> list[Notification]:
    """One user's notification feed, newest first. ``unread=True`` →
    only unread; ``False`` → only read; ``None`` → both."""
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread is True:
        stmt = stmt.where(Notification.read_at.is_(None))
    elif unread is False:
        stmt = stmt.where(Notification.read_at.is_not(None))
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def mark_all_unread_read(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    when: datetime,
) -> int:
    """Bulk UPDATE ``read_at = when`` for every unread row of one
    user. Returns the count touched. Caller commits."""
    result = await session.execute(
        update(Notification)
        .where(Notification.user_id == user_id)
        .where(Notification.read_at.is_(None))
        .values(read_at=when)
    )
    return int(result.rowcount or 0)


def insert_notification(session: AsyncSession, notification: Notification) -> None:
    """Register an already-constructed Notification for INSERT."""
    session.add(notification)


# --- Preferences --------------------------------------------------------


async def get_preference_enabled(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    type_: str,
    channel: NotificationChannel,
) -> bool | None:
    """Return the explicit ``enabled`` value for a (user, type,
    channel) row, or ``None`` when no row exists. Caller picks the
    default — in-app defaults ON, email defaults OFF."""
    result = await session.execute(
        select(NotificationPreference.enabled)
        .where(NotificationPreference.user_id == user_id)
        .where(NotificationPreference.type == type_)
        .where(NotificationPreference.channel == channel)
    )
    return result.scalar_one_or_none()


async def list_preferences_for_user(
    session: AsyncSession, *, user_id: uuid.UUID
) -> list[NotificationPreference]:
    """Every explicit preference row this user has set. Absent
    ``(type, channel)`` pairs are intentionally omitted; the
    frontend treats absence as the channel's default."""
    result = await session.execute(
        select(NotificationPreference)
        .where(NotificationPreference.user_id == user_id)
        .order_by(NotificationPreference.type, NotificationPreference.channel)
    )
    return list(result.scalars().all())


async def list_preferences_for_user_and_type(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    type_: str,
) -> list[NotificationPreference]:
    """Per-channel preferences for one user + one notification type.
    Used by the upsert path to return the freshly-merged set."""
    result = await session.execute(
        select(NotificationPreference)
        .where(NotificationPreference.user_id == user_id)
        .where(NotificationPreference.type == type_)
        .order_by(NotificationPreference.channel)
    )
    return list(result.scalars().all())


async def upsert_preference(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    type_: str,
    channel: NotificationChannel,
    enabled: bool,
    when: datetime,
) -> None:
    """``INSERT ... ON CONFLICT DO UPDATE`` against the
    ``uq_notification_pref_user_type_channel`` constraint. Caller
    commits in batch after upserting every channel in the payload."""
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
            set_={"enabled": enabled, "updated_at": when},
        )
    )
    await session.execute(stmt)


# --- Cross-module helper ------------------------------------------------


async def lookup_user_email_by_legacy_uuid(
    session: AsyncSession, *, legacy_uuid: uuid.UUID
) -> str | None:
    """Resolve ``legacy_uuid → tbl_user_info.email`` via the layered
    User mapper's bigint PK. Returns ``None`` when the user / profile
    is missing or the email field is empty. Used by the email
    fan-out path in the notify() pipeline."""
    result = await session.execute(
        select(UserInfo.email)
        .join(User, User.id == UserInfo.member_id)
        .where(User.legacy_uuid == legacy_uuid)
    )
    email = result.scalar_one_or_none()
    if email is None or not str(email).strip():
        return None
    return str(email).strip()


__all__ = [
    "get_notification_for_user",
    "get_preference_enabled",
    "insert_notification",
    "list_notifications_for_user",
    "list_preferences_for_user",
    "list_preferences_for_user_and_type",
    "lookup_user_email_by_legacy_uuid",
    "mark_all_unread_read",
    "upsert_preference",
]
