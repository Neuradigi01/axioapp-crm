"""Data-access layer for the auth module.

Pure query helpers — no transactions, no audit, no commits. Leaf
module; never imports a `service.py`.

Liveness checks (`revoked_at is None`, `expires_at > now`) are kept on
the caller side because each authentication path interprets a
revoked / expired session differently — middleware raises 401, the WS
upgrade closes with policy-violation, the logout endpoint returns
204 no-op. The DAL just returns the row.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.models import AuthSession


async def get_auth_session(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> AuthSession | None:
    """Resolve an auth-session row by id.

    `user_id` adds a second predicate so a caller can verify the
    session belongs to the user it's acting on — used by
    `POST /auth/sessions/{id}/revoke` to refuse cross-user revokes
    without leaking the existence of someone else's session.
    """
    stmt = select(AuthSession).where(AuthSession.id == session_id)
    if user_id is not None:
        stmt = stmt.where(AuthSession.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


__all__ = ["get_auth_session"]
