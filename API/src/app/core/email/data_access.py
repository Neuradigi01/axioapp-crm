"""Data-access layer for the core email module.

Pure query helpers — no transactions, no audit, no token decryption,
no token-refresh logic. Leaf module; never imports a ``service.py``.

Five operations:

  * ``list_accounts_query``         — tenant-scoped list, newest connection
    first, optional ``user_id`` filter for "my accounts" view.
  * ``get_account_by_id``           — tenant-scoped single-row read.
  * ``get_account_by_id_unscoped``  — raw SQL bypass of the
    ``do_orm_execute`` tenant filter for Celery / webhook entry points
    that have no JWT and need to learn the org from the row itself.
    Same pattern as ``core.integrations.service.get_by_webhook_secret``
    and ``core.email.gmail.push.find_account_by_email``.
  * ``find_account_for_external``   — the upsert's pre-read on
    ``(user_id, provider, external_account_id)``.
  * ``insert_account``              — caller commits.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.email.models import (
    EmailAccount,
    EmailAccountProvider,
    EmailAccountSyncState,
)


async def list_accounts_query(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
) -> list[EmailAccount]:
    """All accounts visible to the active tenant, newest connection
    first. Pass ``user_id`` to scope to one user's accounts."""
    stmt = select(EmailAccount).order_by(EmailAccount.connected_at.desc())
    if user_id is not None:
        stmt = stmt.where(EmailAccount.user_id == user_id)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def get_account_by_id(session: AsyncSession, *, account_id: uuid.UUID) -> EmailAccount | None:
    """Tenant-scoped single-row read. ``None`` if missing OR if the
    caller's org cannot see it (RLS hides cross-tenant rows)."""
    return (
        await session.execute(select(EmailAccount).where(EmailAccount.id == account_id))
    ).scalar_one_or_none()


async def get_account_by_id_unscoped(
    session: AsyncSession, *, account_id: uuid.UUID
) -> EmailAccount | None:
    """Load an account BYPASSING the tenant filter — for Celery tasks
    and webhook entry points that have no JWT and need to learn the
    org from the row itself before setting ``RequestContext.org_id``.

    Uses raw SQL to defeat the ``do_orm_execute`` auto-filter.
    """
    sql = text(
        """
        SELECT id, org_id, user_id, provider, external_account_id,
               email_address, display_name, access_token_enc,
               refresh_token_enc, token_expires_at, scopes_granted,
               sync_cursor, sync_state, last_sync_at, last_sync_error,
               daily_sent_count, daily_sent_reset_at, connected_at,
               disconnected_at, disconnected_by
        FROM tbl_email_accounts
        WHERE id = :account_id
        LIMIT 1
        """
    )
    row = (await session.execute(sql, {"account_id": str(account_id)})).mappings().first()
    if row is None:
        return None

    return EmailAccount(
        id=row["id"],
        org_id=row["org_id"],
        user_id=row["user_id"],
        provider=EmailAccountProvider(row["provider"]),
        external_account_id=row["external_account_id"],
        email_address=row["email_address"],
        display_name=row["display_name"],
        access_token_enc=row["access_token_enc"],
        refresh_token_enc=row["refresh_token_enc"],
        token_expires_at=row["token_expires_at"],
        scopes_granted=row["scopes_granted"] or [],
        sync_cursor=row["sync_cursor"],
        sync_state=EmailAccountSyncState(row["sync_state"]),
        last_sync_at=row["last_sync_at"],
        last_sync_error=row["last_sync_error"],
        daily_sent_count=row["daily_sent_count"],
        daily_sent_reset_at=row["daily_sent_reset_at"],
        connected_at=row["connected_at"],
        disconnected_at=row["disconnected_at"],
        disconnected_by=row["disconnected_by"],
    )


async def find_account_for_external(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    provider: EmailAccountProvider,
    external_account_id: str,
) -> EmailAccount | None:
    """The upsert's pre-read: locate an existing row for the
    ``(user_id, provider, external_account_id)`` tuple so the service
    can decide between INSERT and in-place UPDATE."""
    return (
        await session.execute(
            select(EmailAccount)
            .where(EmailAccount.user_id == user_id)
            .where(EmailAccount.provider == provider)
            .where(EmailAccount.external_account_id == external_account_id)
        )
    ).scalar_one_or_none()


def insert_account(session: AsyncSession, account: EmailAccount) -> None:
    """Register an already-constructed EmailAccount for INSERT."""
    session.add(account)


async def find_default_sendable(
    session: AsyncSession, *, org_id: uuid.UUID
) -> EmailAccount | None:
    """The org's ``is_default=True`` OAuth mailbox, or ``None``.

    Also gates on ``sync_state != disconnected`` and a non-null
    ``refresh_token_enc`` so a stale ``is_default=True`` flag on a
    revoked mailbox never wins the resolver — ``service.disconnect``
    auto-demotes on the way out, but this guard makes the resolver
    robust to any future path that flips ``sync_state`` without
    demoting.
    """
    result = await session.execute(
        select(EmailAccount).where(
            EmailAccount.org_id == org_id,
            EmailAccount.is_default.is_(True),
            EmailAccount.sync_state != EmailAccountSyncState.disconnected,
            EmailAccount.refresh_token_enc.is_not(None),
        )
    )
    return result.scalar_one_or_none()


async def clear_all_defaults(
    session: AsyncSession, *, org_id: uuid.UUID
) -> None:
    """Reset ``is_default=false`` on every OAuth mailbox in the org.
    Caller commits — used as the OAuth half of the polymorphic
    :func:`email_senders.service.set_default_sender` flip so exactly
    one row across both tables carries the flag."""
    await session.execute(
        update(EmailAccount)
        .where(EmailAccount.org_id == org_id)
        .values(is_default=False)
    )


def set_default(row: EmailAccount) -> None:
    """Mutate the row in-place: ``is_default=True``. Caller commits."""
    row.is_default = True


__all__ = [
    "clear_all_defaults",
    "find_account_for_external",
    "find_default_sendable",
    "get_account_by_id",
    "get_account_by_id_unscoped",
    "insert_account",
    "list_accounts_query",
    "set_default",
]
