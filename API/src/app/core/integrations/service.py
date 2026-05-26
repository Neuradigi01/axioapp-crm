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

import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.integrations.crypto import (
    decrypt_optional,
    encrypt,
    encrypt_optional,
)
from src.app.core.integrations.models import (
    Integration,
    IntegrationDLQ,
    IntegrationProvider,
    IntegrationStatus,
    IntegrationSubscription,
)
from src.app.core.integrations.schemas import (
    IntegrationSubscriptionCreate,
    IntegrationSubscriptionUpdate,
    IntegrationUpsert,
)


def _new_webhook_secret() -> str:
    """A 32-byte url-safe random token. Long enough that brute-forcing
    the per-tenant webhook path is computationally infeasible."""
    return secrets.token_urlsafe(32)


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
            # Mint the webhook secret on first connect so the Settings
            # UI can show the per-tenant webhook URL immediately. The
            # secret survives across reconnects unless the row went
            # through disconnect (which nulls it).
            webhook_secret=_new_webhook_secret(),
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
        # Re-mint on reconnect after a disconnect — old URL becomes
        # immediately invalid, so a leaked webhook URL can't be revived
        # by an ex-admin re-OAuthing a stolen account.
        if existing.webhook_secret is None:
            existing.webhook_secret = _new_webhook_secret()
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
    # Null the webhook secret so the public webhook URL stops
    # authenticating immediately — Google/Meta deliveries against the
    # old URL will 401, which tells them to stop retrying.
    row.webhook_secret = None
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


# --- Webhook secret lookup ------------------------------------------------


async def get_by_webhook_secret(
    session: AsyncSession,
    *,
    webhook_secret: str,
) -> Optional[Integration]:
    """Resolve an integration row by its webhook URL discriminator.
    Used by the public webhook endpoint to authenticate the inbound
    delivery — no JWT, no tenant header; the secret IS the auth.

    Returns None for any unknown / nulled secret. The endpoint then
    returns 401 + emits the `integration.webhook.invalid_signature`
    audit event with the request IP.

    This is the only DB read in the codebase that bypasses the org
    tenant filter (the receiver has no tenant context yet — we LEARN
    it from this lookup). The bypass is safe: `webhook_secret` is
    UNIQUE (per migration 0049) so the predicate selects at most one
    row, and the secret itself is the authentication factor.
    """
    if not webhook_secret:
        return None
    # `do_orm_execute` tenant filter would reject this query (no
    # active org_id). Use a raw connection-level SELECT to bypass.
    from sqlalchemy import text

    sql = text(
        """
        SELECT id, org_id, provider, status, account_id, account_label,
               access_token_enc, refresh_token_enc, token_expires_at,
               scopes, last_error, connected_at, connected_by,
               disconnected_at, disconnected_by, updated_at,
               webhook_secret
        FROM integrations
        WHERE webhook_secret = :secret
        LIMIT 1
        """
    )
    row = (
        await session.execute(sql, {"secret": webhook_secret})
    ).mappings().first()
    if row is None:
        return None
    integration = Integration(
        id=row["id"],
        org_id=row["org_id"],
        provider=IntegrationProvider(row["provider"]),
        status=IntegrationStatus(row["status"]),
        account_id=row["account_id"],
        account_label=row["account_label"],
        access_token_enc=row["access_token_enc"],
        refresh_token_enc=row["refresh_token_enc"],
        token_expires_at=row["token_expires_at"],
        scopes=row["scopes"],
        last_error=row["last_error"],
        connected_at=row["connected_at"],
        connected_by=row["connected_by"],
        disconnected_at=row["disconnected_at"],
        disconnected_by=row["disconnected_by"],
        updated_at=row["updated_at"],
        webhook_secret=row["webhook_secret"],
    )
    return integration


async def rotate_webhook_secret(
    session: AsyncSession,
    *,
    provider: IntegrationProvider,
) -> Optional[Integration]:
    """Issue a fresh webhook secret for the (active-tenant, provider)
    integration. Returns the updated row or None if no row exists.
    Old URL stops authenticating immediately — the Settings UI must
    pull the new URL after this call. Audited as
    `integration.webhook.rotated`."""
    row = await get(session, provider=provider)
    if row is None:
        return None
    row.webhook_secret = _new_webhook_secret()
    await session.commit()
    await session.refresh(row)
    await audit.log(
        "integration.webhook.rotated",
        entity_type="integration",
        entity_id=row.id,
        after={"provider": provider.value},
    )
    return row


# --- Subscription CRUD ----------------------------------------------------


async def list_subscriptions(
    session: AsyncSession,
    *,
    integration_id: Optional[uuid.UUID] = None,
) -> list[IntegrationSubscription]:
    """All subscriptions in the active tenant, optionally filtered to
    one integration. RLS authorises the org scope via the ORM tenant
    filter — no explicit org_id WHERE clause needed."""
    stmt = select(IntegrationSubscription).order_by(
        IntegrationSubscription.created_at.desc()
    )
    if integration_id is not None:
        stmt = stmt.where(
            IntegrationSubscription.integration_id == integration_id
        )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def create_subscription(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: IntegrationSubscriptionCreate,
) -> IntegrationSubscription:
    """Insert a new (integration, external_form_id) subscription.
    Raises 409 on duplicate — the `uq_integration_subscriptions_form`
    constraint is what makes this safe to call from a re-render of the
    Settings form picker."""
    # Verify the integration exists in this tenant (the FK + RLS would
    # catch a foreign-tenant ref, but a friendly 404 is better than a
    # 500 from a constraint violation).
    parent = (
        await session.execute(
            select(Integration).where(
                Integration.id == payload.integration_id
            )
        )
    ).scalar_one_or_none()
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"integration {payload.integration_id} not found",
        )
    row = IntegrationSubscription(
        org_id=org_id,
        integration_id=payload.integration_id,
        external_form_id=payload.external_form_id,
        external_form_label=payload.external_form_label,
        field_mapping=dict(payload.field_mapping or {}),
        enabled=payload.enabled,
    )
    session.add(row)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Subscription already exists for form "
                f"{payload.external_form_id} on this integration."
            ),
        )
    await session.refresh(row)
    await audit.log(
        "integration.subscription.created",
        entity_type="integration_subscription",
        entity_id=row.id,
        after={
            "integration_id": str(payload.integration_id),
            "external_form_id": payload.external_form_id,
        },
    )
    return row


async def update_subscription(
    session: AsyncSession,
    *,
    subscription_id: uuid.UUID,
    payload: IntegrationSubscriptionUpdate,
) -> IntegrationSubscription:
    """Partial update of a subscription. 404 if missing."""
    row = (
        await session.execute(
            select(IntegrationSubscription).where(
                IntegrationSubscription.id == subscription_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="subscription not found",
        )
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(row, field, value)
    await session.commit()
    await session.refresh(row)
    await audit.log(
        "integration.subscription.updated",
        entity_type="integration_subscription",
        entity_id=row.id,
        after=changes,
    )
    return row


async def delete_subscription(
    session: AsyncSession,
    *,
    subscription_id: uuid.UUID,
) -> bool:
    """Hard-delete a subscription. Returns True if a row was removed.
    Future ad-form deliveries for the removed `external_form_id` will
    DLQ with reason `no_subscription`."""
    row = (
        await session.execute(
            select(IntegrationSubscription).where(
                IntegrationSubscription.id == subscription_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    await audit.log(
        "integration.subscription.deleted",
        entity_type="integration_subscription",
        entity_id=subscription_id,
    )
    return True


async def find_subscription(
    session: AsyncSession,
    *,
    integration_id: uuid.UUID,
    external_form_id: str,
) -> Optional[IntegrationSubscription]:
    """Locate the subscription row for an inbound webhook payload.
    Worker calls this with the integration + form id from the payload.
    Returns None if no subscription matches (worker DLQs with
    `no_subscription`)."""
    return (
        await session.execute(
            select(IntegrationSubscription)
            .where(
                IntegrationSubscription.integration_id == integration_id
            )
            .where(
                IntegrationSubscription.external_form_id
                == external_form_id
            )
        )
    ).scalar_one_or_none()


# --- DLQ list + count helpers --------------------------------------------


async def list_dlq(
    session: AsyncSession,
    *,
    page: int = 1,
    size: int = 50,
    provider: Optional[IntegrationProvider] = None,
    include_replayed: bool = True,
) -> tuple[list[IntegrationDLQ], int]:
    """Paginated DLQ list for the active tenant. Returns (rows, total).

    `provider` filters to one platform (Settings UI uses this to show
    only Google or only Meta failures). `include_replayed=False`
    excludes rows that have been replayed OR discarded — drives the
    Step-8 status panel's "X deliveries failed in the last 24h"
    counter (which doesn't double-count rows the operator already
    addressed).
    """
    filters = []
    if provider is not None:
        filters.append(IntegrationDLQ.provider == provider)
    if not include_replayed:
        filters.append(IntegrationDLQ.replayed_at.is_(None))

    base = (
        select(IntegrationDLQ)
        .where(*filters)
        .order_by(IntegrationDLQ.created_at.desc())
    )
    count_stmt = (
        select(func.count()).select_from(IntegrationDLQ).where(*filters)
    )
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(
            base.offset((page - 1) * size).limit(size)
        )
    ).scalars().all()
    return list(rows), total


async def discard_dlq(
    session: AsyncSession,
    *,
    dlq_id: uuid.UUID,
) -> Optional[IntegrationDLQ]:
    """Soft-discard a DLQ row — sets `replayed_at = now()` with
    `replayed_by = NULL`. The NULL `replayed_by` is the discriminator:
    a real replay always records the actor, a discard never does.
    The row survives for forensic trail; the status counter excludes
    it (via `include_replayed=False`).

    Returns the updated row, or None if the row doesn't exist.
    Idempotent — re-discarding (or discarding an already-replayed row)
    is a no-op."""
    row = await get_dlq(session, dlq_id=dlq_id)
    if row is None:
        return None
    if row.replayed_at is not None:
        return row
    row.replayed_at = datetime.now(timezone.utc)
    row.replayed_by = None
    await session.commit()
    await session.refresh(row)
    await audit.log(
        "integration.webhook.dlq_discarded",
        entity_type="integration_dlq",
        entity_id=row.id,
        after={"provider": row.provider.value},
    )
    return row


async def update_subscription_mapping(
    session: AsyncSession,
    *,
    subscription_id: uuid.UUID,
    mapping: dict,
) -> IntegrationSubscription:
    """Replace the subscription's `field_mapping` JSONB. The mapping
    is `{ad_field_name: crm_target_key}`; the router validates target
    keys against `leads.imports.targets.list_target_keys()` before
    calling here so we never persist an invalid CRM target."""
    row = (
        await session.execute(
            select(IntegrationSubscription).where(
                IntegrationSubscription.id == subscription_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="subscription not found",
        )
    row.field_mapping = dict(mapping)
    await session.commit()
    await session.refresh(row)
    await audit.log(
        "integration.subscription.mapping_updated",
        entity_type="integration_subscription",
        entity_id=row.id,
        after={"field_count": len(mapping)},
    )
    return row


async def get_dlq(
    session: AsyncSession, *, dlq_id: uuid.UUID
) -> Optional[IntegrationDLQ]:
    """Fetch a single DLQ row by id (RLS-scoped). Used by the replay
    endpoint before it re-enqueues."""
    return (
        await session.execute(
            select(IntegrationDLQ).where(IntegrationDLQ.id == dlq_id)
        )
    ).scalar_one_or_none()


__all__ = [
    "create_subscription",
    "decrypt_tokens",
    "delete_subscription",
    "discard_dlq",
    "disconnect",
    "find_subscription",
    "get",
    "get_by_webhook_secret",
    "get_dlq",
    "list_all",
    "list_dlq",
    "list_subscriptions",
    "rotate_webhook_secret",
    "update_subscription",
    "update_subscription_mapping",
    "upsert",
]
