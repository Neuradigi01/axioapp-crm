"""Pure CRUD for the BYOK provider-key store.

No transactions, no permission checks, no business logic — those
live in ``service.py``. Every function returns ORM objects or Core
result rows to the caller.

The ``TenantScoped`` auto-filter in :mod:`src.app.shared.orm` scopes
every SELECT against ``AiProviderKey`` / ``OrgAiCostBudget`` by the
request-context ``org_id`` — belt+braces on top of the Postgres RLS
policy from migration ``0198``. The one exception is
:func:`count_assistants_by_key_id`, which is a **stub** returning 0
until Step 5 introduces the assistants table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.integrations.ai.models import (
    AiProvider,
    AiProviderKey,
    OrgAiCostBudget,
)

# --- Provider keys -------------------------------------------------------


async def insert_key(db: AsyncSession, **values: object) -> AiProviderKey:
    """Stage an INSERT of ``AiProviderKey`` — caller is responsible
    for db.flush() + db.commit() from the service layer. Returns the
    ORM object with ``id`` populated after flush.

    The unique constraint on ``(org_id, provider, fingerprint_sha256)``
    surfaces re-adds of the same key material as ``IntegrityError`` —
    the service translates that to a 409 with the existing row's
    masked last-4.
    """
    row = AiProviderKey(**values)
    db.add(row)
    return row


async def list_keys(
    db: AsyncSession,
    *,
    provider: AiProvider | None = None,
    include_revoked: bool = False,
) -> list[AiProviderKey]:
    stmt = select(AiProviderKey)
    if provider is not None:
        stmt = stmt.where(AiProviderKey.provider == provider)
    if not include_revoked:
        stmt = stmt.where(AiProviderKey.revoked_at.is_(None))
    stmt = stmt.order_by(AiProviderKey.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_key_by_id(
    db: AsyncSession,
    key_id: uuid.UUID,
) -> AiProviderKey | None:
    """RLS + TenantScoped filter ensure this is only ever a hit when
    the row belongs to the caller's org. Cross-org lookups return
    ``None`` — the service surfaces that as 404."""
    stmt = select(AiProviderKey).where(AiProviderKey.id == key_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_key_by_fingerprint(
    db: AsyncSession,
    *,
    provider: AiProvider,
    fingerprint_sha256: bytes,
) -> AiProviderKey | None:
    """Used by the service's dedup path — returns the existing row
    so the 409 response can carry its masked last-4."""
    stmt = select(AiProviderKey).where(
        AiProviderKey.provider == provider,
        AiProviderKey.fingerprint_sha256 == fingerprint_sha256,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def mark_test_result(
    db: AsyncSession,
    *,
    key_id: uuid.UUID,
    status: str,
    error: str | None,
    tested_at: datetime,
) -> None:
    """Stage an UPDATE of the ``test_status`` / ``test_last_at`` /
    ``test_last_error`` columns. Service commits."""
    stmt = (
        update(AiProviderKey)
        .where(AiProviderKey.id == key_id)
        .values(
            test_status=status,
            test_last_at=tested_at,
            test_last_error=error,
            updated_at=tested_at,
        )
    )
    await db.execute(stmt)


async def delete_key(db: AsyncSession, key_id: uuid.UUID) -> None:
    """Hard-delete. Caller's service layer has already verified 0
    assistant references + committed the caller-facing transaction
    boundary."""
    row = await get_key_by_id(db, key_id)
    if row is not None:
        await db.delete(row)


async def count_assistants_by_key_id(
    db: AsyncSession,  # noqa: ARG001  — kept for signature parity with Step 5
    key_id: uuid.UUID,  # noqa: ARG001
) -> int:
    """STUB — replaced in Step 5 when ``core.ai_assistants.models``
    lands ``tbl_ai_assistants.key_id``. Returns 0 today so DELETE
    always succeeds in the empty-assistants world of Steps 1-4.

    Step 5 rewrites this function body to:
        stmt = select(func.count()).select_from(AiAssistant).where(
            AiAssistant.key_id == key_id
        )
        result = await db.execute(stmt)
        return result.scalar_one()
    """
    return 0


async def reassign_key_references(
    db: AsyncSession,  # noqa: ARG001
    *,
    from_key_id: uuid.UUID,  # noqa: ARG001
    to_key_id: uuid.UUID,  # noqa: ARG001
) -> int:
    """STUB — replaced in Step 5. Step 5's body:
        stmt = update(AiAssistant).where(
            AiAssistant.key_id == from_key_id
        ).values(key_id=to_key_id)
        result = await db.execute(stmt)
        return result.rowcount

    Raises ``NotImplementedError`` in Step 1 — the reassign endpoint
    is exposed by the router but the service refuses the call until
    Step 5 wires the assistants table. Dev can still test the
    endpoint's cross-org guard + validation flow; the actual UPDATE
    is deferred.
    """
    raise NotImplementedError(
        "reassign_key_references is stubbed until tasks/ai-assistants "
        "Step 5 introduces tbl_ai_assistants.key_id"
    )


# --- Budget --------------------------------------------------------------


async def get_budget(db: AsyncSession, org_id: uuid.UUID) -> OrgAiCostBudget | None:
    stmt = select(OrgAiCostBudget).where(OrgAiCostBudget.org_id == org_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def insert_budget(db: AsyncSession, org_id: uuid.UUID) -> OrgAiCostBudget:
    row = OrgAiCostBudget(org_id=org_id)
    db.add(row)
    return row


async def update_budget_caps(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    daily_cap_usd: object | None,
    monthly_cap_usd: object | None,
) -> None:
    values: dict[str, object] = {"updated_at": func.now()}
    if daily_cap_usd is not None:
        values["daily_cap_usd"] = daily_cap_usd
    if monthly_cap_usd is not None:
        values["monthly_cap_usd"] = monthly_cap_usd
    stmt = update(OrgAiCostBudget).where(OrgAiCostBudget.org_id == org_id).values(**values)
    await db.execute(stmt)


async def update_budget_spent(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    spent_today_usd: object,
    spent_month_usd: object,
    day_bucket: object,
    month_bucket: object,
) -> None:
    stmt = (
        update(OrgAiCostBudget)
        .where(OrgAiCostBudget.org_id == org_id)
        .values(
            spent_today_usd=spent_today_usd,
            spent_month_usd=spent_month_usd,
            day_bucket=day_bucket,
            month_bucket=month_bucket,
            updated_at=func.now(),
        )
    )
    await db.execute(stmt)


__all__ = [
    "count_assistants_by_key_id",
    "delete_key",
    "get_budget",
    "get_key_by_fingerprint",
    "get_key_by_id",
    "insert_budget",
    "insert_key",
    "list_keys",
    "mark_test_result",
    "reassign_key_references",
    "update_budget_caps",
    "update_budget_spent",
]
