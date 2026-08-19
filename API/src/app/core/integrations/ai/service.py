"""Service layer for the BYOK provider-key store.

Owns the transaction boundary (only file in this sub-module that
commits), business validation, encryption/decryption around the DAL,
the per-user rate limiter for the test endpoint, and the day/month
rollover logic on the budget row.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.integrations.ai import crypto as ai_crypto
from src.app.core.integrations.ai import data_access as _da
from src.app.core.integrations.ai.models import (
    AiProvider,
    AiProviderKey,
    AiProviderTestStatus,
    OrgAiCostBudget,
)
from src.app.core.integrations.ai.schemas import (
    AiProviderKeyCreate,
    AiProviderKeyReassign,
    OrgAiCostBudgetUpdate,
)

# --- Test-endpoint rate limiter -----------------------------------------
# In-process defaultdict per user_id → deque of recent call timestamps.
# 5 calls per minute + 30 per day, both enforced. Simple + good enough
# for the operator-facing surface; the public embed endpoint gets
# Redis-backed rate limiting in Step 14.

_RATE_LIMIT_PER_MINUTE = 5
_RATE_LIMIT_PER_DAY = 30
_MINUTE_SECONDS = 60
_DAY_SECONDS = 60 * 60 * 24

_test_calls: dict[uuid.UUID, deque[float]] = defaultdict(deque)


def _check_test_rate_limit(user_id: uuid.UUID) -> None:
    """Raise 429 if the caller has exceeded either window."""
    now = time.monotonic()
    calls = _test_calls[user_id]
    # Prune anything older than a day (biggest window).
    while calls and now - calls[0] > _DAY_SECONDS:
        calls.popleft()
    if len(calls) >= _RATE_LIMIT_PER_DAY:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"reason": "test_rate_limit_daily", "retry_after_seconds": _DAY_SECONDS},
        )
    recent_minute = sum(1 for t in calls if now - t <= _MINUTE_SECONDS)
    if recent_minute >= _RATE_LIMIT_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"reason": "test_rate_limit_minute", "retry_after_seconds": _MINUTE_SECONDS},
        )
    calls.append(now)


# --- Provider-key CRUD --------------------------------------------------


def _fingerprint(api_key: str) -> bytes:
    return hashlib.sha256(api_key.encode("utf-8")).digest()


def _last4(api_key: str) -> str:
    # Everything after the last 4 chars, padded so tiny junk keys don't crash.
    return api_key[-4:] if len(api_key) >= 4 else api_key.rjust(4, "*")


async def create_provider_key(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: AiProviderKeyCreate,
) -> AiProviderKey:
    """Encrypt with AES-GCM/AAD, insert, commit. Dedup surfaces as
    409 via the unique constraint on ``(org_id, provider, fingerprint)``.
    """
    fingerprint = _fingerprint(payload.api_key)

    # Fast-path dedup — one SELECT saves a wasted encrypt on the common
    # case where the operator re-adds a key they already stored. The
    # unique constraint still enforces this in a concurrent-add race.
    existing = await _da.get_key_by_fingerprint(
        db,
        provider=payload.provider,
        fingerprint_sha256=fingerprint,
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "reason": "key_already_stored",
                "existing_key_id": str(existing.id),
                "last4": existing.last4,
            },
        )

    # Pre-generate the id so AAD is stable across encrypt + row insert.
    key_id = uuid.uuid4()
    key_version = 1
    aad = ai_crypto.build_aad(str(org_id), str(key_id), key_version)
    ciphertext, nonce = ai_crypto.encrypt(payload.api_key.encode("utf-8"), aad)

    row = await _da.insert_key(
        db,
        id=key_id,
        org_id=org_id,
        provider=payload.provider,
        label=payload.label,
        encrypted_key=ciphertext,
        nonce=nonce,
        key_version=key_version,
        fingerprint_sha256=fingerprint,
        last4=_last4(payload.api_key),
    )
    try:
        await db.flush()
        await db.commit()
    except IntegrityError:
        # Concurrent add hit the unique constraint between the
        # fast-path check and the INSERT.
        await db.rollback()
        existing = await _da.get_key_by_fingerprint(
            db,
            provider=payload.provider,
            fingerprint_sha256=fingerprint,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "reason": "key_already_stored",
                "existing_key_id": str(existing.id) if existing else None,
                "last4": existing.last4 if existing else None,
            },
        ) from None
    await db.refresh(row)
    return row


async def list_provider_keys(
    db: AsyncSession,
    *,
    provider: AiProvider | None = None,
) -> list[AiProviderKey]:
    return await _da.list_keys(db, provider=provider, include_revoked=False)


async def get_decrypted_key(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    key_id: uuid.UUID,
) -> str:
    """Fetch + decrypt the plaintext API key for internal callers
    (Step 2's LLM adapter, Step 9's chat runtime). NEVER returned
    through any HTTP response.
    """
    row = await _da.get_key_by_id(db, key_id)
    if row is None or row.org_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    aad = ai_crypto.build_aad(str(org_id), str(row.id), row.key_version)
    try:
        plaintext = ai_crypto.decrypt(row.encrypted_key, row.nonce, aad)
    except ai_crypto.AADMismatchError as exc:
        # Generic error — never surface the ciphertext or the AAD.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"reason": "provider_key_undecryptable"},
        ) from exc
    return plaintext.decode("utf-8")


async def test_provider_key(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    key_id: uuid.UUID,
) -> AiProviderKey:
    """Ping the provider with the stored key. Updates ``test_status``
    + ``test_last_at`` + ``test_last_error``. Rate-limited per user.

    Delegates the actual probe to
    :func:`src.app.shared.llm.factory` — the adapter's ``probe()``
    hits the provider's cheapest endpoint (OpenAI: ``models.list``)
    to verify auth without spending completion tokens.
    """
    _check_test_rate_limit(user_id)

    row = await _da.get_key_by_id(db, key_id)
    if row is None or row.org_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Local import — avoid a module-load cycle: factory imports the
    # openai adapter which imports back into this service module.
    from src.app.shared.llm import factory as llm_factory

    tested_at = datetime.now(UTC)
    client = llm_factory(row.provider.value, db=db, org_id=org_id, key_id=key_id)
    probe = await client.probe()
    if probe.ok:
        result_status = AiProviderTestStatus.success.value
        error: str | None = None
    else:
        result_status = AiProviderTestStatus.failed.value
        error = probe.detail or "provider_probe_failed"

    await _da.mark_test_result(
        db,
        key_id=key_id,
        status=result_status,
        error=error,
        tested_at=tested_at,
    )
    await db.commit()
    refreshed = await _da.get_key_by_id(db, key_id)
    return cast(AiProviderKey, refreshed)


async def delete_provider_key(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    key_id: uuid.UUID,
) -> None:
    """Hard-delete the key iff no assistants reference it. Assistants
    table lands in Step 5; until then the reference count is always
    0 (stub in DAL) so delete always succeeds."""
    row = await _da.get_key_by_id(db, key_id)
    if row is None or row.org_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    ref_count = await _da.count_assistants_by_key_id(db, key_id)
    if ref_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "reason": "referenced_by_assistants",
                "reference_count": ref_count,
                "key_id": str(key_id),
            },
        )

    await _da.delete_key(db, key_id)
    await db.commit()


async def reassign_provider_key(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: AiProviderKeyReassign,
) -> int:
    """Swap every assistant's ``key_id`` from ``from_key_id`` to
    ``to_key_id``. Cross-org keys are refused with 404 (never leak
    existence). Actual UPDATE is a DAL stub raising
    ``NotImplementedError`` until Step 5.
    """
    from_row = await _da.get_key_by_id(db, payload.from_key_id)
    to_row = await _da.get_key_by_id(db, payload.to_key_id)
    if from_row is None or from_row.org_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if to_row is None or to_row.org_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if from_row.id == to_row.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"reason": "from_and_to_are_the_same_key"},
        )

    rowcount = await _da.reassign_key_references(
        db,
        from_key_id=payload.from_key_id,
        to_key_id=payload.to_key_id,
    )
    await db.commit()
    return rowcount


# --- Budget --------------------------------------------------------------


def _today_utc() -> date:
    return datetime.now(UTC).date()


def _month_bucket_utc() -> str:
    now = datetime.now(UTC)
    return f"{now.year:04d}-{now.month:02d}"


async def get_or_create_budget(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> OrgAiCostBudget:
    """Idempotent — first call inserts the row with server defaults;
    subsequent calls return the existing row."""
    row = await _da.get_budget(db, org_id)
    if row is not None:
        return row
    new_row = await _da.insert_budget(db, org_id)
    await db.flush()
    await db.commit()
    await db.refresh(new_row)
    return new_row


async def update_budget(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: OrgAiCostBudgetUpdate,
) -> OrgAiCostBudget:
    row = await get_or_create_budget(db, org_id=org_id)
    await _da.update_budget_caps(
        db,
        org_id=org_id,
        daily_cap_usd=payload.daily_cap_usd,
        monthly_cap_usd=payload.monthly_cap_usd,
    )
    await db.commit()
    refreshed = await _da.get_budget(db, org_id)
    return cast(OrgAiCostBudget, refreshed or row)


async def charge_budget(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    cost_usd: Decimal,
    dry_run: bool = False,
) -> tuple[bool, str | None]:
    """Advisory helper called by the chat runtime (Step 9) before
    every LLM call. Returns ``(allowed, reason)`` — false with
    ``daily_cap_hit`` / ``monthly_cap_hit`` when either cap would be
    exceeded.

    Handles day/month rollover — if ``day_bucket`` has changed since
    the last write, ``spent_today_usd`` is reset before adding.
    ``dry_run=True`` computes the answer without mutating (used to
    short-circuit before the LLM call); the runtime calls again with
    ``dry_run=False`` after the LLM completes to record the actual
    cost.
    """
    row = await get_or_create_budget(db, org_id=org_id)
    today = _today_utc()
    month = _month_bucket_utc()

    spent_today = row.spent_today_usd if row.day_bucket == today else Decimal("0")
    spent_month = row.spent_month_usd if row.month_bucket == month else Decimal("0")

    projected_today = spent_today + cost_usd
    projected_month = spent_month + cost_usd

    if projected_today > row.daily_cap_usd:
        return False, "daily_cap_hit"
    if projected_month > row.monthly_cap_usd:
        return False, "monthly_cap_hit"

    if dry_run:
        return True, None

    await _da.update_budget_spent(
        db,
        org_id=org_id,
        spent_today_usd=projected_today,
        spent_month_usd=projected_month,
        day_bucket=today,
        month_bucket=month,
    )
    await db.commit()
    return True, None


__all__ = [
    "charge_budget",
    "create_provider_key",
    "delete_provider_key",
    "get_decrypted_key",
    "get_or_create_budget",
    "list_provider_keys",
    "reassign_provider_key",
    "test_provider_key",
    "update_budget",
]
