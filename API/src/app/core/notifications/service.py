"""Service layer for notifications.

Three public entry points:

- **`notify(user_id, type, title, ...)`** — non-raising helper any
  module imports to send a notification. Honours the recipient's
  `in_app` preference (skips writing if disabled); always pushes
  over WebSocket when the user has `in_app` enabled. Also dispatches
  one email when the recipient has explicitly opted into the `email`
  channel for the type AND `email_renderer.render_email()` recognises
  the type (currently the `appointment.*` family). SMTP failures are
  logged + audited but do not roll back the persisted in-app row.
  Push delivery is still deferred — channel exists in the schema but
  no sender is wired.
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

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.notifications import data_access as _da
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

    Email channel is best-effort: if the recipient has explicitly
    opted into `(type, email)` AND the renderer recognises the type,
    one email is dispatched. SMTP failure is logged + audited but
    does NOT roll back the persisted in-app notification.
    """
    try:
        ctx_token = set_context(RequestContext(org_id=org_id, user_id=user_id))
        notification_out: NotificationOut | None = None
        email_enabled = False
        recipient_email: str | None = None
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
                _da.insert_notification(session, notification)
                await session.commit()
                await session.refresh(notification)

                notification_out = NotificationOut.model_validate(notification)
                wire = notification_out.model_dump(mode="json")

                # Email channel is opt-in (default OFF) — check the
                # explicit preference row before bothering to look up
                # the recipient's address.
                email_enabled = await _email_opted_in(
                    session, user_id=user_id, type_=type
                )
                if email_enabled:
                    recipient_email = await _da.lookup_user_email_by_legacy_uuid(
                        session, legacy_uuid=user_id
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

        if (
            email_enabled
            and notification_out is not None
            and recipient_email is not None
        ):
            await _send_email_for(notification_out, to=recipient_email)
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
    row = await _da.get_preference_enabled(
        session, user_id=user_id, type_=type_, channel=channel
    )
    return True if row is None else row


async def _email_opted_in(
    session: AsyncSession, *, user_id: uuid.UUID, type_: str
) -> bool:
    """Email defaults to OFF — only ON if an explicit row says enabled=true.

    Different default from in-app: tenants shouldn't suddenly start
    receiving emails when a new notification type is introduced.
    """
    row = await _da.get_preference_enabled(
        session,
        user_id=user_id,
        type_=type_,
        channel=NotificationChannel.email,
    )
    return bool(row) if row is not None else False


async def _send_email_for(notif: NotificationOut, *, to: str) -> None:
    """Best-effort email send + audit. Swallows + logs every failure."""
    from src.app.core.audit import service as audit
    from src.app.core.notifications.email_renderer import render_email
    from src.app.shared.email import Email, get_email_backend

    try:
        rendered = render_email(notif)
        if rendered is None:
            return
        subject, html_body, text_body = rendered
        await get_email_backend().send(
            Email(
                to=to,
                subject=subject,
                body_text=text_body,
                body_html=html_body,
            )
        )
        await audit.log(
            "notification.email.sent",
            org_id=notif.org_id,
            user_id=notif.user_id,
            after={
                "notification_id": str(notif.id),
                "type": notif.type,
                "to": to,
            },
        )
    except Exception:
        logger.warning(
            "notifications.email.send failed notification_id=%s type=%s user=%s",
            notif.id,
            notif.type,
            notif.user_id,
            exc_info=True,
        )
        await audit.log(
            "notification.email.failed",
            org_id=notif.org_id,
            user_id=notif.user_id,
            after={
                "notification_id": str(notif.id),
                "type": notif.type,
                "to": to,
            },
        )


async def list_for_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    unread: Optional[bool] = None,
    limit: int = 50,
) -> list[Notification]:
    return await _da.list_notifications_for_user(
        session, user_id=user_id, unread=unread, limit=limit
    )


async def mark_read(
    session: AsyncSession, *, user_id: uuid.UUID, notification_id: uuid.UUID
) -> Optional[Notification]:
    """Mark a notification read. Returns the updated row or None if it
    doesn't exist / belongs to another user (we don't leak existence)."""
    notification = await _da.get_notification_for_user(
        session, notification_id=notification_id, user_id=user_id
    )
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
    touched = await _da.mark_all_unread_read(
        session, user_id=user_id, when=now
    )
    await session.commit()
    return touched


# --- Preferences ---


async def get_preferences(
    session: AsyncSession, *, user_id: uuid.UUID
) -> list[NotificationPreference]:
    """Return every explicit preference row this user has set."""
    return await _da.list_preferences_for_user(session, user_id=user_id)


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

    when = datetime.now(timezone.utc)
    for channel, enabled in channel_values.items():
        await _da.upsert_preference(
            session,
            org_id=org_id,
            user_id=user_id,
            type_=type_,
            channel=channel,
            enabled=enabled,
            when=when,
        )
    if channel_values:
        await session.commit()

    return await _da.list_preferences_for_user_and_type(
        session, user_id=user_id, type_=type_
    )


__all__ = [
    "NotificationChannel",
    "get_preferences",
    "list_for_user",
    "mark_all_read",
    "mark_read",
    "notify",
    "update_preferences",
]
