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

import re
import secrets
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.integrations import data_access as _da
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
from src.app.core.pipelines.service import get_pipeline_by_key
from src.app.shared.audit import log_entity_change

# Same constant the leads service uses for its own stage validation.
# Duplicated (not imported) to avoid a leads → integrations dependency.
_LEADS_PIPELINE_KEY = "leads"


def _new_webhook_secret() -> str:
    """A 32-byte url-safe random token. Long enough that brute-forcing
    the per-tenant webhook path is computationally infeasible."""
    return secrets.token_urlsafe(32)


async def _validate_pipeline_stage(
    session: AsyncSession,
    *,
    stage_key: str,
) -> None:
    """Reject a per-form `pipeline_stage` that isn't part of the org's
    leads pipeline. Mirrors `leads.service._resolve_initial_stage` so a
    subscription that persists here won't blow up later at ingest time
    when the shared ingest service applies the same check.

    Raises 422 if the stage key doesn't resolve; 400 if the org has no
    leads pipeline configured at all (same error text `leads.service`
    surfaces on the create path)."""
    pipeline = await get_pipeline_by_key(session, key=_LEADS_PIPELINE_KEY)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("no 'leads' pipeline configured for this org — install the pack first"),
        )
    stage_keys = {s.key for s in pipeline.stages}
    if stage_key not in stage_keys:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(f"pipeline_stage {stage_key!r} is not part of the leads pipeline"),
        )


async def get(
    session: AsyncSession,
    *,
    provider: IntegrationProvider,
) -> Integration | None:
    """Return the single (org, provider) row for the active tenant, or
    None if the org has never connected this provider."""
    return await _da.get_integration_for_provider(session, provider)


async def list_all(session: AsyncSession) -> list[Integration]:
    """Every integration row for the active tenant."""
    return await _da.list_integrations(session)


async def upsert(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: IntegrationUpsert,
    actor_id: uuid.UUID | None,
) -> Integration:
    """Insert-or-update the (org, provider) row. Encrypts the plaintext
    tokens before write."""
    provider_enum = IntegrationProvider(payload.provider)
    existing = await _da.find_integration_for_org_provider(
        session, org_id=org_id, provider=provider_enum
    )

    access_enc = encrypt(payload.access_token)
    refresh_enc = encrypt_optional(payload.refresh_token)
    now = datetime.now(UTC)

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
            webhook_secret=_new_webhook_secret(),
        )
        _da.insert_integration(session, row)
    else:
        existing.account_id = payload.account_id
        existing.account_label = payload.account_label
        existing.access_token_enc = access_enc
        existing.refresh_token_enc = refresh_enc
        existing.token_expires_at = payload.token_expires_at
        existing.scopes = list(payload.scopes) if payload.scopes else None
        existing.status = IntegrationStatus.connected
        existing.last_error = None
        existing.connected_at = now
        existing.connected_by = actor_id
        existing.disconnected_at = None
        existing.disconnected_by = None
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
    actor_id: uuid.UUID | None,
) -> Integration | None:
    """Clear the row's tokens + flip status to `disconnected`. Returns
    the updated row, or None if no row exists for this (org, provider)."""
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
    row.disconnected_at = datetime.now(UTC)
    row.disconnected_by = actor_id
    # Null the webhook secret so the public webhook URL stops
    # authenticating immediately.
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


def decrypt_tokens(integration: Integration) -> tuple[str, str | None]:
    """Return `(access_token, refresh_token)` in plaintext."""
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
) -> Integration | None:
    """Resolve an integration row by its webhook URL discriminator.
    Used by the public webhook endpoint to authenticate the inbound
    delivery — no JWT, no tenant header; the secret IS the auth."""
    return await _da.get_integration_by_webhook_secret_unscoped(
        session, webhook_secret=webhook_secret
    )


async def rotate_webhook_secret(
    session: AsyncSession,
    *,
    provider: IntegrationProvider,
) -> Integration | None:
    """Issue a fresh webhook secret for the (active-tenant, provider)
    integration."""
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
    integration_id: uuid.UUID | None = None,
) -> list[IntegrationSubscription]:
    """All subscriptions in the active tenant, optionally filtered to
    one integration."""
    return await _da.list_subscriptions_query(session, integration_id=integration_id)


async def create_subscription(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: IntegrationSubscriptionCreate,
) -> IntegrationSubscription:
    """Insert a new (integration, external_form_id) subscription."""
    parent = await _da.get_integration_by_id(session, payload.integration_id)
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"integration {payload.integration_id} not found",
        )
    if payload.pipeline_stage is not None:
        await _validate_pipeline_stage(session, stage_key=payload.pipeline_stage)
    row = IntegrationSubscription(
        org_id=org_id,
        integration_id=payload.integration_id,
        external_form_id=payload.external_form_id,
        external_form_label=payload.external_form_label,
        field_mapping=dict(payload.field_mapping or {}),
        enabled=payload.enabled,
        pipeline_stage=payload.pipeline_stage,
    )
    _da.insert_subscription(session, row)
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
        ) from None
    await session.refresh(row)
    await log_entity_change(
        action="integration.subscription.created",
        entity_type="integration_subscription",
        entity_id=row.id,
        after={
            "integration_id": str(payload.integration_id),
            "external_form_id": payload.external_form_id,
        },
    )
    return row


# --- Step 13: auto-attach forms on Page subscribe ------------------------


# Backend mirror of the frontend `field-mapping-editor` DEFAULT_RULES.
# Compared case-insensitively against each ad-form question key. When
# the operator hits "Use defaults" in the mapping editor they get the
# same target-for-key result — auto-attach and manual editor stay in
# lockstep, no surprise flips when the operator opens the modal after a
# subscribe.
_DEFAULT_MAPPING_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^full[_ ]?name$", re.IGNORECASE), "contact.full_name"),
    (re.compile(r"^name$", re.IGNORECASE), "contact.full_name"),
    (re.compile(r"^first[_ ]?name$", re.IGNORECASE), "contact.full_name"),
    (re.compile(r"^phone(?:[_ ]?number)?$", re.IGNORECASE), "contact.phone"),
    (re.compile(r"^mobile(?:[_ ]?number)?$", re.IGNORECASE), "contact.phone"),
    (re.compile(r"^email$", re.IGNORECASE), "contact.email"),
    (re.compile(r"^work[_ ]?email$", re.IGNORECASE), "contact.email"),
)


def _default_mapping_for_questions(questions: Iterable[str]) -> dict[str, str]:
    """Apply the heuristic rules to a form's question keys — returns a
    fresh `{form_field: crm_target}` dict. Fields that don't match any
    rule are omitted (same effect as picking "(Ignore)" in the editor —
    worker drops them at ingest). Duplicate question keys keep the
    first match; Meta and Google both guarantee unique keys per form."""
    out: dict[str, str] = {}
    for name in questions:
        if not isinstance(name, str) or not name or name in out:
            continue
        for pattern, target in _DEFAULT_MAPPING_RULES:
            if pattern.match(name):
                out[name] = target
                break
    return out


async def auto_attach_forms(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    integration_id: uuid.UUID,
    forms: Sequence[tuple[str, str, Sequence[str]]],
) -> int:
    """Idempotently ensure a subscription row exists for every form
    passed in. Each `forms` entry is `(external_form_id, label, question_keys)`.

    Called by `subscribe_page_endpoint` (Meta) after Meta confirms the
    Page subscription — CRM industry standard is "subscribe = leads
    start flowing," not "subscribe then manually attach each form."

    Idempotency guarantees:
      - Existing rows are NEVER modified. Operator edits to
        `field_mapping`, `pipeline_stage`, and `enabled` are safe
        across re-subscribes.
      - Only forms without a row get a fresh row with the heuristic
        default mapping.

    Returns the number of NEW rows inserted (0 when nothing new)."""
    existing_ids = await _da.list_subscription_form_ids(session, integration_id=integration_id)
    inserted = 0
    for form_id, label, questions in forms:
        if form_id in existing_ids:
            continue
        row = IntegrationSubscription(
            org_id=org_id,
            integration_id=integration_id,
            external_form_id=form_id,
            external_form_label=label or None,
            field_mapping=_default_mapping_for_questions(questions),
            enabled=True,
        )
        _da.insert_subscription(session, row)
        inserted += 1
    if inserted:
        await session.commit()
    return inserted


async def update_subscription(
    session: AsyncSession,
    *,
    subscription_id: uuid.UUID,
    payload: IntegrationSubscriptionUpdate,
) -> IntegrationSubscription:
    """Partial update of a subscription. 404 if missing."""
    row = await _da.get_subscription_by_id(session, subscription_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="subscription not found",
        )
    changes = payload.model_dump(exclude_unset=True)
    # Absent-vs-null distinguishes "leave alone" from "clear override";
    # only validate when the caller actually supplied a non-null string.
    new_stage = changes.get("pipeline_stage")
    if "pipeline_stage" in changes and new_stage is not None:
        await _validate_pipeline_stage(session, stage_key=new_stage)
    for field, value in changes.items():
        setattr(row, field, value)
    await session.commit()
    await session.refresh(row)
    await log_entity_change(
        action="integration.subscription.updated",
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
    """Hard-delete a subscription. Returns True if a row was removed."""
    row = await _da.get_subscription_by_id(session, subscription_id)
    if row is None:
        return False
    await _da.delete_subscription_row(session, row)
    await session.commit()
    await log_entity_change(
        action="integration.subscription.deleted",
        entity_type="integration_subscription",
        entity_id=subscription_id,
    )
    return True


async def find_subscription(
    session: AsyncSession,
    *,
    integration_id: uuid.UUID,
    external_form_id: str,
) -> IntegrationSubscription | None:
    """Locate the subscription row for an inbound webhook payload."""
    return await _da.find_subscription_for_form(
        session,
        integration_id=integration_id,
        external_form_id=external_form_id,
    )


# --- DLQ list + count helpers --------------------------------------------


async def list_dlq(
    session: AsyncSession,
    *,
    page: int = 1,
    size: int = 50,
    provider: IntegrationProvider | None = None,
    include_replayed: bool = True,
) -> tuple[list[IntegrationDLQ], int]:
    """Paginated DLQ list for the active tenant."""
    return await _da.list_dlq_query(
        session,
        page=page,
        size=size,
        provider=provider,
        include_replayed=include_replayed,
    )


async def discard_dlq(
    session: AsyncSession,
    *,
    dlq_id: uuid.UUID,
) -> IntegrationDLQ | None:
    """Soft-discard a DLQ row — sets `replayed_at = now()` with
    `replayed_by = NULL`."""
    row = await get_dlq(session, dlq_id=dlq_id)
    if row is None:
        return None
    if row.replayed_at is not None:
        return row
    row.replayed_at = datetime.now(UTC)
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
    """Replace the subscription's `field_mapping` JSONB."""
    row = await _da.get_subscription_by_id(session, subscription_id)
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


async def get_dlq(session: AsyncSession, *, dlq_id: uuid.UUID) -> IntegrationDLQ | None:
    """Fetch a single DLQ row by id (RLS-scoped)."""
    return await _da.get_dlq_by_id(session, dlq_id)


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
