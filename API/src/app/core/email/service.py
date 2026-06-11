"""Service layer for `email_accounts` — upsert/disconnect/list +
the token-decryption + sync-state helpers.

Tenant context is the caller's responsibility (router sets it via
the existing middleware; OAuth callbacks in Steps 2 + 3 set it
explicitly after resolving the target org from the signed `state`).

The provider-specific code (Gmail in Step 2, Microsoft in Step 3)
reads plaintext tokens via `decrypt_tokens(account)`. Tokens are
never held longer than the API call that needs them — no
module-level caching, no logging.

Encryption reuses `core.integrations.crypto` (the same Fernet key).
No second key to manage; Rule 10 "no parallel infra" wins over the
spec's suggestion of a separate `EMAIL_TOKEN_KEY`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.email.models import (
    EmailAccount,
    EmailAccountProvider,
    EmailAccountSyncState,
)
from src.app.core.email.oauth import TokenSet, get_provider
from src.app.core.email.schemas import EmailAccountUpsert
from src.app.core.integrations.crypto import (
    decrypt_optional,
    encrypt,
    encrypt_optional,
)


# A token within this window is treated as expired so the provider
# client preemptively refreshes before hitting the wire — defends
# against clock skew + the long-tail of refresh latency.
_REFRESH_LEEWAY = timedelta(minutes=5)


# --- Reads ---------------------------------------------------------------


async def list_accounts(
    session: AsyncSession,
    *,
    user_id: Optional[uuid.UUID] = None,
) -> list[EmailAccount]:
    """Every account row visible to the active tenant. Pass
    `user_id` to filter to that user's accounts (the rep's "my
    accounts" view); omit for the Owner admin view across the
    whole org.

    RLS authorises the org scope via the ORM tenant filter — no
    explicit `org_id` WHERE clause needed.
    """
    stmt = select(EmailAccount).order_by(EmailAccount.connected_at.desc())
    if user_id is not None:
        stmt = stmt.where(EmailAccount.user_id == user_id)
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def get_account(
    session: AsyncSession, *, account_id: uuid.UUID
) -> Optional[EmailAccount]:
    """Single row by id (RLS-scoped). None if missing OR if the
    caller's org cannot see it (RLS hides cross-tenant rows)."""
    return (
        await session.execute(
            select(EmailAccount).where(EmailAccount.id == account_id)
        )
    ).scalar_one_or_none()


async def get_account_unscoped(
    session: AsyncSession, *, account_id: uuid.UUID
) -> Optional[EmailAccount]:
    """Load an account by id BYPASSING the tenant filter — used by
    Step 4's Celery tasks which have no JWT and need to learn the
    org from the row itself before setting context.

    Uses raw SQL to defeat the `do_orm_execute` auto-filter (which
    is a no-op when `RequestContext.org_id is None` anyway, but
    being explicit defends against a future tightening that would
    deny rows in the unscoped case).

    Mirrors the same pattern as `core.integrations.service.
    get_by_webhook_secret` and `core.email.gmail.push.
    find_account_by_email` — both load cross-tenant for webhook /
    daemon entry points that have no JWT to derive context from.
    """
    from sqlalchemy import text

    sql = text(
        """
        SELECT id, org_id, user_id, provider, external_account_id,
               email_address, display_name, access_token_enc,
               refresh_token_enc, token_expires_at, scopes_granted,
               sync_cursor, sync_state, last_sync_at, last_sync_error,
               daily_sent_count, daily_sent_reset_at, connected_at,
               disconnected_at, disconnected_by
        FROM email_accounts
        WHERE id = :account_id
        LIMIT 1
        """
    )
    row = (
        await session.execute(sql, {"account_id": str(account_id)})
    ).mappings().first()
    if row is None:
        return None
    from src.app.core.email.models import (
        EmailAccountProvider,
        EmailAccountSyncState,
    )

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


# --- Writes --------------------------------------------------------------


async def upsert(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: EmailAccountUpsert,
    actor_id: Optional[uuid.UUID] = None,
) -> EmailAccount:
    """Insert-or-update the (user, provider, external_account_id)
    row. Encrypts the plaintext tokens before write — the caller
    passes plaintext (just out of the OAuth exchange); ciphertext is
    what hits Postgres.

    Sets `sync_state='pending'` so the sync daemon (Step 4) picks
    up the row on its next tick and runs the backfill. Stamps
    `connected_at`, clears any prior `last_sync_error` and
    `disconnected_at`/`disconnected_by`.

    Idempotent: a re-connect for the same external account updates
    tokens in place — the UNIQUE constraint enforces single-row.

    Emits `email.account.connected` (best-effort).
    """
    provider_enum = EmailAccountProvider(payload.provider)
    existing = (
        await session.execute(
            select(EmailAccount)
            .where(EmailAccount.user_id == user_id)
            .where(EmailAccount.provider == provider_enum)
            .where(
                EmailAccount.external_account_id
                == payload.external_account_id
            )
        )
    ).scalar_one_or_none()

    access_enc = encrypt(payload.access_token)
    refresh_enc = encrypt_optional(payload.refresh_token)
    now = datetime.now(timezone.utc)

    if existing is None:
        row = EmailAccount(
            org_id=org_id,
            user_id=user_id,
            provider=provider_enum,
            external_account_id=payload.external_account_id,
            email_address=payload.email_address,
            display_name=payload.display_name,
            access_token_enc=access_enc,
            refresh_token_enc=refresh_enc,
            token_expires_at=payload.token_expires_at,
            scopes_granted=list(payload.scopes_granted),
            sync_state=EmailAccountSyncState.pending,
            last_sync_error=None,
            connected_at=now,
            disconnected_at=None,
            disconnected_by=None,
        )
        session.add(row)
    else:
        existing.email_address = payload.email_address
        existing.display_name = payload.display_name
        existing.access_token_enc = access_enc
        existing.refresh_token_enc = refresh_enc
        existing.token_expires_at = payload.token_expires_at
        existing.scopes_granted = list(payload.scopes_granted)
        existing.sync_state = EmailAccountSyncState.pending
        existing.last_sync_error = None
        existing.connected_at = now
        existing.disconnected_at = None
        existing.disconnected_by = None
        row = existing

    await session.commit()
    await session.refresh(row)

    await audit.log(
        "email.account.connected",
        entity_type="email_account",
        entity_id=row.id,
        after={
            "provider": provider_enum.value,
            "email_address": payload.email_address,
            "scopes_granted": list(payload.scopes_granted),
        },
        user_id=actor_id,
    )
    return row


async def disconnect(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    actor_id: Optional[uuid.UUID] = None,
) -> Optional[EmailAccount]:
    """Clear the row's tokens + flip `sync_state` to `disconnected`.
    Returns the updated row, or None if the row doesn't exist (or
    is hidden by RLS).

    Idempotent — disconnecting an already-disconnected row is a
    no-op (no second audit event, no second commit).

    Emits `email.account.disconnected` (best-effort).
    """
    row = await get_account(session, account_id=account_id)
    if row is None:
        return None
    if row.sync_state == EmailAccountSyncState.disconnected:
        return row

    row.access_token_enc = None
    row.refresh_token_enc = None
    row.token_expires_at = None
    row.sync_cursor = None
    row.sync_state = EmailAccountSyncState.disconnected
    row.disconnected_at = datetime.now(timezone.utc)
    row.disconnected_by = actor_id

    await session.commit()
    await session.refresh(row)

    await audit.log(
        "email.account.disconnected",
        entity_type="email_account",
        entity_id=row.id,
        after={
            "provider": row.provider.value,
            "email_address": row.email_address,
        },
        user_id=actor_id,
    )
    return row


async def update_sync_state(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    sync_state: EmailAccountSyncState,
    cursor: Optional[str] = None,
    error: Optional[str] = None,
) -> Optional[EmailAccount]:
    """Helper for the sync daemon (Step 4) and the provider sync
    routines (Steps 2 + 3). Flips `sync_state`, optionally advances
    `sync_cursor` and stamps `last_sync_error`.

    Returns the updated row or None if missing. No audit event —
    sync transitions are too frequent to audit per-row; the daemon
    emits per-tick summaries instead.
    """
    row = await get_account(session, account_id=account_id)
    if row is None:
        return None
    row.sync_state = sync_state
    if cursor is not None:
        row.sync_cursor = cursor
    if sync_state == EmailAccountSyncState.live:
        row.last_sync_at = datetime.now(timezone.utc)
        row.last_sync_error = None
    elif sync_state == EmailAccountSyncState.error:
        row.last_sync_error = error
    await session.commit()
    await session.refresh(row)
    return row


# --- Token decrypt + refresh --------------------------------------------


def decrypt_tokens(account: EmailAccount) -> tuple[str, Optional[str]]:
    """Return `(access_token, refresh_token)` in plaintext. The
    access token is always present for a row that isn't
    `disconnected`; the refresh token may be None on providers
    that don't always issue one (Microsoft historically; Gmail
    only on the first grant unless `prompt=consent` is set).

    Raises `RuntimeError` if the row has no encrypted access token
    — that means the account is `disconnected` and the caller has a
    bug. Provider clients should call `refresh_if_expired` first;
    that path either returns the existing plaintext or refreshes +
    persists the new ciphertext before this is called.
    """
    if account.access_token_enc is None:
        raise RuntimeError(
            f"email_account {account.id} has no access token "
            f"(sync_state={account.sync_state.value}); reconnect required"
        )
    # Defer the import to avoid a tight cyclical dependency between
    # email.service and integrations.crypto at module-load time.
    from src.app.core.integrations.crypto import decrypt as _decrypt

    return (
        _decrypt(account.access_token_enc),
        decrypt_optional(account.refresh_token_enc),
    )


async def refresh_if_expired(
    session: AsyncSession,
    *,
    account: EmailAccount,
) -> TokenSet:
    """If the cached access token is within 5 min of expiring (or
    has no expiry stamp), exchange the refresh token for a fresh
    set via the provider's `refresh()`. Persists the new
    ciphertext + expiry under the same `account` row.

    Returns the plaintext `TokenSet` ready for the caller's
    outbound API call. The plaintext does NOT survive past the
    caller's HTTP request — there is no caching layer.

    Raises:
      - `RuntimeError` if the row is disconnected.
      - `RuntimeError` if no provider is registered for
        `account.provider` (configuration drift).
      - Whatever the provider's `refresh()` raises — typically an
        HTTP error from the token endpoint; the caller catches +
        flips the row to `sync_state='error'` via
        `update_sync_state(...)`.
    """
    access_plain, refresh_plain = decrypt_tokens(account)
    now = datetime.now(timezone.utc)

    needs_refresh = (
        account.token_expires_at is None
        or account.token_expires_at - now <= _REFRESH_LEEWAY
    )
    if not needs_refresh:
        return TokenSet(
            access_token=access_plain,
            refresh_token=refresh_plain,
            expires_in_seconds=None,
            scopes_granted=list(account.scopes_granted),
        )

    if refresh_plain is None:
        # Some providers (Microsoft on some tenant policies) do not
        # issue a refresh token. The account must be reconnected.
        raise RuntimeError(
            f"email_account {account.id} has no refresh token; "
            "reconnect required to re-mint credentials"
        )

    provider = get_provider(account.provider.value)
    if provider is None:
        raise RuntimeError(
            f"no OAuth provider registered for "
            f"{account.provider.value!r} — check startup adapter imports"
        )
    fresh = await provider.refresh(refresh_token=refresh_plain)

    account.access_token_enc = encrypt(fresh.access_token)
    if fresh.refresh_token is not None:
        # Provider sometimes returns a NEW refresh token; persist it
        # so the next refresh uses the latest. Some providers return
        # None and want us to keep the prior refresh token.
        account.refresh_token_enc = encrypt(fresh.refresh_token)
    if fresh.expires_in_seconds is not None:
        account.token_expires_at = now + timedelta(
            seconds=fresh.expires_in_seconds
        )
    if fresh.scopes_granted:
        account.scopes_granted = list(fresh.scopes_granted)
    await session.commit()
    await session.refresh(account)
    return fresh


__all__ = [
    "decrypt_tokens",
    "disconnect",
    "get_account",
    "get_account_unscoped",
    "list_accounts",
    "refresh_if_expired",
    "update_sync_state",
    "upsert",
]
