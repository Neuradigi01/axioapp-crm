"""Service layer for `integrations` — upsert/disconnect/list + the
single token-decryption helper. Tenant context is the caller's
responsibility (router sets it via the existing middleware; OAuth
callbacks in Steps 2 + 4 will set it explicitly after resolving the
target org from the OAuth state).

The provider-specific code (Google in Step 2, Meta in Step 4) reads
plaintext tokens by calling `decrypt_tokens()` on a freshly-loaded
`Integration` row. Tokens are never held longer than the API call that
needs them — no module-level caching, no logging.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.integrations.crypto import (
    decrypt_optional,
    encrypt,
    encrypt_optional,
)
from src.app.core.integrations.models import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
)
from src.app.core.integrations.schemas import IntegrationUpsert


async def get(
    session: AsyncSession,
    *,
    provider: IntegrationProvider,
) -> Optional[Integration]:
    """Return the single (org, provider) row for the active tenant, or
    None if the org has never connected this provider. Relies on the
    tenant-context filter from `TenantScoped` for org isolation."""
    return (
        await session.execute(
            select(Integration).where(Integration.provider == provider)
        )
    ).scalar_one_or_none()


async def list_all(session: AsyncSession) -> list[Integration]:
    """Every integration row for the active tenant. Empty for orgs
    that haven't connected anything yet — the Settings UI then shows
    a "Connect" CTA for both providers."""
    rows = (
        await session.execute(
            select(Integration).order_by(Integration.provider)
        )
    ).scalars().all()
    return list(rows)


async def upsert(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: IntegrationUpsert,
    actor_id: Optional[uuid.UUID],
) -> Integration:
    """Insert-or-update the (org, provider) row. Encrypts the plaintext
    tokens before write — the caller passes plaintext (just out of the
    OAuth exchange); ciphertext is what hits Postgres.

    Sets `status='connected'`, stamps `connected_at` + `connected_by`,
    clears any previous `last_error`. Emits `integration.connected`.

    Idempotent: a second connect for the same `(org, provider)` updates
    tokens in place — the UNIQUE constraint enforces single-row.
    """
    provider_enum = IntegrationProvider(payload.provider)
    existing = (
        await session.execute(
            select(Integration)
            .where(Integration.org_id == org_id)
            .where(Integration.provider == provider_enum)
        )
    ).scalar_one_or_none()

    access_enc = encrypt(payload.access_token)
    refresh_enc = encrypt_optional(payload.refresh_token)
    now = datetime.now(timezone.utc)

    if existing is None:
        row = Integration(
            org_id=org_id,
            provider=provider_enum,
            account_id=payload.account_id,
            account_label=payload.account_label,
            access_token_enc=access_enc,
            refresh_token_enc=refresh_enc,
            token_expires_at=payload.token_expires_at,
            scopes=list(payload.scopes) if payload.scopes else None,
            status=IntegrationStatus.connected,
            last_error=None,
            connected_at=now,
            connected_by=actor_id,
            disconnected_at=None,
            disconnected_by=None,
        )
        session.add(row)
    else:
        existing.account_id = payload.account_id
        existing.account_label = payload.account_label
        existing.access_token_enc = access_enc
        existing.refresh_token_enc = refresh_enc
        existing.token_expires_at = payload.token_expires_at
        existing.scopes = (
            list(payload.scopes) if payload.scopes else None
        )
        existing.status = IntegrationStatus.connected
        existing.last_error = None
        existing.connected_at = now
        existing.connected_by = actor_id
        existing.disconnected_at = None
        existing.disconnected_by = None
        row = existing

    await session.commit()
    await session.refresh(row)

    await audit.log(
        "integration.connected",
        entity_type="integration",
        entity_id=row.id,
        after={
            "provider": provider_enum.value,
            "account_id": payload.account_id,
            "account_label": payload.account_label,
            "scopes": list(payload.scopes) if payload.scopes else [],
        },
    )
    return row


async def disconnect(
    session: AsyncSession,
    *,
    provider: IntegrationProvider,
    actor_id: Optional[uuid.UUID],
) -> Optional[Integration]:
    """Clear the row's tokens + flip status to `disconnected`. Returns
    the updated row, or None if no row exists for this (org, provider).

    Idempotent — calling disconnect on an already-disconnected row is a
    no-op (no second audit event, no error).

    Emits `integration.disconnected`."""
    row = await get(session, provider=provider)
    if row is None:
        return None
    if row.status == IntegrationStatus.disconnected:
        return row

    row.access_token_enc = None
    row.refresh_token_enc = None
    row.token_expires_at = None
    row.scopes = None
    row.status = IntegrationStatus.disconnected
    row.disconnected_at = datetime.now(timezone.utc)
    row.disconnected_by = actor_id
    await session.commit()
    await session.refresh(row)

    await audit.log(
        "integration.disconnected",
        entity_type="integration",
        entity_id=row.id,
        after={"provider": provider.value},
    )
    return row


def decrypt_tokens(integration: Integration) -> tuple[str, Optional[str]]:
    """Return `(access_token, refresh_token)` in plaintext. The access
    token is always present for a `connected` row; the refresh token may
    be None (not every provider returns one on every grant — e.g. Google
    only returns refresh tokens on the FIRST OAuth grant for a given
    client, unless `prompt=consent` is set).

    The caller MUST be the provider-specific API client that's about to
    make an outbound call — NEVER the API surface that returns data to
    a browser. Plaintext tokens leaving this function should be passed
    directly into the HTTP request and not held longer than necessary.

    Raises `RuntimeError` if the row has no encrypted access token (the
    integration is disconnected or never had tokens stored — caller bug).
    """
    if integration.access_token_enc is None:
        raise RuntimeError(
            f"integration {integration.id} has no access token "
            f"(status={integration.status.value}); reconnect required"
        )
    from src.app.core.integrations.crypto import decrypt as _decrypt

    return (
        _decrypt(integration.access_token_enc),
        decrypt_optional(integration.refresh_token_enc),
    )


__all__ = [
    "decrypt_tokens",
    "disconnect",
    "get",
    "list_all",
    "upsert",
]
