"""Pure CRUD helpers for :class:`GoogleCalendarToken`.

Manager spec 2026-06-25 layered convention — this file is
DAL-only: no transactions, no business logic, no permission checks.
Just single-purpose read + write helpers the service layer
composes. Callers own the transaction (:mod:`service.py` commits).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.integrations.google_calendar.models import GoogleCalendarToken


async def get_token_for_user(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: int,
) -> GoogleCalendarToken | None:
    """Return the row for ``(org_id, user_id)`` or ``None``.

    Reads through the RLS gate — the tenant listener on the session
    already scoped the query, so cross-org rows are unreachable
    even if a caller passes a stale org_id.
    """
    stmt = select(GoogleCalendarToken).where(
        GoogleCalendarToken.org_id == org_id,
        GoogleCalendarToken.user_id == user_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_active_token_for_user(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: int,
) -> GoogleCalendarToken | None:
    """Like :func:`get_token_for_user` but filters to ``status='active'``.

    The Step-4 sync task uses this so revoked / errored rows never get
    picked up for reconciliation attempts.
    """
    stmt = select(GoogleCalendarToken).where(
        GoogleCalendarToken.org_id == org_id,
        GoogleCalendarToken.user_id == user_id,
        GoogleCalendarToken.status == "active",
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def add_token(
    session: AsyncSession, token: GoogleCalendarToken
) -> GoogleCalendarToken:
    """Stage an INSERT. Caller flushes / commits."""
    session.add(token)
    return token


async def delete_token_for_user(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: int,
) -> int:
    """Hard-delete the row for ``(org_id, user_id)``. Returns the row
    count so callers can distinguish "was connected → now disconnected"
    from "wasn't connected in the first place"."""
    stmt = delete(GoogleCalendarToken).where(
        GoogleCalendarToken.org_id == org_id,
        GoogleCalendarToken.user_id == user_id,
    )
    result = await session.execute(stmt)
    return int(result.rowcount or 0)


async def update_access_token(
    session: AsyncSession,
    *,
    token_id: uuid.UUID,
    access_token_encrypted: str,
    access_token_expires_at: datetime,
) -> None:
    """Refresh-token success path — persists the newly-issued short-
    lived access token. Called from :mod:`oauth.get_valid_access_token`."""
    stmt = (
        update(GoogleCalendarToken)
        .where(GoogleCalendarToken.id == token_id)
        .values(
            access_token_encrypted=access_token_encrypted,
            access_token_expires_at=access_token_expires_at,
            status="active",
            last_error=None,
        )
    )
    await session.execute(stmt)


async def mark_status(
    session: AsyncSession,
    *,
    token_id: uuid.UUID,
    status: str,
    error: str | None = None,
) -> None:
    """Surface a persistent problem on the connection card — the
    frontend polls ``/status`` and renders ``last_error`` verbatim so
    the operator knows why sync stopped."""
    stmt = (
        update(GoogleCalendarToken)
        .where(GoogleCalendarToken.id == token_id)
        .values(status=status, last_error=error)
    )
    await session.execute(stmt)


async def touch_last_synced(
    session: AsyncSession,
    *,
    token_id: uuid.UUID,
    when: datetime,
) -> None:
    """Bumped by the Step-4 sync task after any successful Google API
    call. Powers the "Last synced: 2 minutes ago" line on the card."""
    stmt = (
        update(GoogleCalendarToken)
        .where(GoogleCalendarToken.id == token_id)
        .values(last_synced_at=when)
    )
    await session.execute(stmt)


__all__ = [
    "add_token",
    "delete_token_for_user",
    "get_active_token_for_user",
    "get_token_for_user",
    "mark_status",
    "touch_last_synced",
    "update_access_token",
]
