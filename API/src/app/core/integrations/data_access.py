"""Data-access layer for the integrations module.

Pure query helpers — no transactions, no audit, no crypto, no
business rules. Leaf module; never imports a ``service.py``.

Operations grouped by entity:

  * Integrations (``tbl_integrations``)
      get_integration_for_provider, list_integrations,
      find_integration_for_org_provider,
      get_integration_by_webhook_secret_unscoped (raw SQL bypass for
      the public webhook entry point that has no JWT),
      insert_integration
  * Subscriptions (``tbl_integration_subscriptions``)
      get_subscription_by_id, list_subscriptions_query,
      find_subscription_for_form, get_integration_by_id (for the
      create-subscription parent existence check), insert_subscription,
      delete_subscription_row
  * DLQ (``tbl_integration_dlq``)
      get_dlq_by_id, list_dlq_query
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.integrations.models import (
    Integration,
    IntegrationDLQ,
    IntegrationProvider,
    IntegrationStatus,
    IntegrationSubscription,
)


# --- Integrations -------------------------------------------------------


async def get_integration_for_provider(
    session: AsyncSession, provider: IntegrationProvider
) -> Optional[Integration]:
    """Single (active-tenant, provider) row, or ``None`` if the org
    has never connected this provider. Tenant scoping is automatic
    via the ORM filter on ``TenantScoped``."""
    return (
        await session.execute(
            select(Integration).where(Integration.provider == provider)
        )
    ).scalar_one_or_none()


async def list_integrations(session: AsyncSession) -> list[Integration]:
    """Every integration row for the active tenant. Empty for orgs
    that haven't connected anything yet."""
    rows = (
        await session.execute(
            select(Integration).order_by(Integration.provider)
        )
    ).scalars().all()
    return list(rows)


async def find_integration_for_org_provider(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    provider: IntegrationProvider,
) -> Optional[Integration]:
    """Upsert pre-read — locate the existing row by the
    ``(org_id, provider)`` composite so the service decides between
    INSERT and in-place UPDATE."""
    return (
        await session.execute(
            select(Integration)
            .where(Integration.org_id == org_id)
            .where(Integration.provider == provider)
        )
    ).scalar_one_or_none()


async def get_integration_by_id(
    session: AsyncSession, integration_id: uuid.UUID
) -> Optional[Integration]:
    """Single-row read by PK. Used by the create-subscription parent
    existence check."""
    return (
        await session.execute(
            select(Integration).where(Integration.id == integration_id)
        )
    ).scalar_one_or_none()


async def get_integration_by_webhook_secret_unscoped(
    session: AsyncSession, *, webhook_secret: str
) -> Optional[Integration]:
    """Load an integration BYPASSING the tenant filter, keyed by its
    ``webhook_secret``. Public webhook entry point has no JWT and
    needs to learn the org from the row itself.

    Uses raw SQL to defeat the ``do_orm_execute`` auto-filter. Safe
    by design: ``webhook_secret`` is UNIQUE (migration 0049) so the
    predicate selects at most one row, and the secret IS the
    authentication factor.
    """
    if not webhook_secret:
        return None
    sql = text(
        """
        SELECT id, org_id, provider, status, account_id, account_label,
               access_token_enc, refresh_token_enc, token_expires_at,
               scopes, last_error, connected_at, connected_by,
               disconnected_at, disconnected_by, updated_at,
               webhook_secret
        FROM tbl_integrations
        WHERE webhook_secret = :secret
        LIMIT 1
        """
    )
    row = (
        await session.execute(sql, {"secret": webhook_secret})
    ).mappings().first()
    if row is None:
        return None
    return Integration(
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


def insert_integration(
    session: AsyncSession, integration: Integration
) -> None:
    """Register an already-constructed Integration for INSERT."""
    session.add(integration)


# --- Subscriptions ------------------------------------------------------


async def get_subscription_by_id(
    session: AsyncSession, subscription_id: uuid.UUID
) -> Optional[IntegrationSubscription]:
    """Single-row read by PK."""
    return (
        await session.execute(
            select(IntegrationSubscription).where(
                IntegrationSubscription.id == subscription_id
            )
        )
    ).scalar_one_or_none()


async def list_subscriptions_query(
    session: AsyncSession,
    *,
    integration_id: Optional[uuid.UUID] = None,
) -> list[IntegrationSubscription]:
    """All subscriptions in the active tenant, optionally filtered to
    one integration. Tenant scope is automatic via the ORM filter."""
    stmt = select(IntegrationSubscription).order_by(
        IntegrationSubscription.created_at.desc()
    )
    if integration_id is not None:
        stmt = stmt.where(
            IntegrationSubscription.integration_id == integration_id
        )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows)


async def find_subscription_for_form(
    session: AsyncSession,
    *,
    integration_id: uuid.UUID,
    external_form_id: str,
) -> Optional[IntegrationSubscription]:
    """Webhook worker lookup — locate the subscription that matches
    one inbound payload's ``(integration_id, external_form_id)`` pair.
    Returns ``None`` when no subscription matches (worker DLQs the
    delivery with ``no_subscription``)."""
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


def insert_subscription(
    session: AsyncSession, subscription: IntegrationSubscription
) -> None:
    """Register an already-constructed IntegrationSubscription for
    INSERT."""
    session.add(subscription)


async def delete_subscription_row(
    session: AsyncSession, subscription: IntegrationSubscription
) -> None:
    """Mark an IntegrationSubscription row for DELETE. Caller commits."""
    await session.delete(subscription)


# --- DLQ ----------------------------------------------------------------


async def get_dlq_by_id(
    session: AsyncSession, dlq_id: uuid.UUID
) -> Optional[IntegrationDLQ]:
    """Single-row DLQ read by PK. Used by the replay endpoint before
    it re-enqueues."""
    return (
        await session.execute(
            select(IntegrationDLQ).where(IntegrationDLQ.id == dlq_id)
        )
    ).scalar_one_or_none()


async def list_dlq_query(
    session: AsyncSession,
    *,
    page: int = 1,
    size: int = 50,
    provider: Optional[IntegrationProvider] = None,
    include_replayed: bool = True,
) -> tuple[list[IntegrationDLQ], int]:
    """Paginated DLQ list for the active tenant. ``include_replayed=
    False`` excludes rows that have been replayed OR discarded —
    drives the status panel's "X failed in last 24h" counter without
    double-counting addressed rows."""
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


__all__ = [
    "delete_subscription_row",
    "find_integration_for_org_provider",
    "find_subscription_for_form",
    "get_dlq_by_id",
    "get_integration_by_id",
    "get_integration_by_webhook_secret_unscoped",
    "get_integration_for_provider",
    "get_subscription_by_id",
    "insert_integration",
    "insert_subscription",
    "list_dlq_query",
    "list_integrations",
    "list_subscriptions_query",
]
