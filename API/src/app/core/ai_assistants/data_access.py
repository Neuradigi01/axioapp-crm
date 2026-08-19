"""Data-access stubs for the AI Assistants module.

Step 6 fills in the CRUD helpers (``list_assistants`` /
``get_assistant_by_id`` / ``insert_assistant`` /
``update_assistant_optimistic`` / ``delete_assistant`` etc). This
file exists in Step 5 with two functions the BYOK provider-key
store (Step 1) needs to call once ``tbl_ai_assistants`` exists:

  * :func:`count_assistants_by_key_id` — how many assistants
    reference a given provider key? Step 1's delete flow blocks
    with 409 when the count is > 0.
  * :func:`reassign_assistant_key_ids` — bulk UPDATE of every
    assistant's ``key_id`` from one key to another. Step 1's
    reassign endpoint calls this inside its own transaction.

Both are the "landing pads" for the Step-1 stub — the stub was
introduced in Step 1's own DAL (returning 0 / raising
``NotImplementedError``) with a documented pointer here. This
step replaces the stub bodies by having Step 1's DAL delegate
to these functions.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.ai_assistants.models import AiAssistant


async def get_assistant_by_id(
    db: AsyncSession,
    assistant_id: uuid.UUID,
) -> AiAssistant | None:
    """RLS + TenantScoped filter ensure this only returns rows
    belonging to the caller's org. Step 6 uses this as the read
    path for ``GET /ai-assistants/{id}``."""
    stmt = select(AiAssistant).where(AiAssistant.id == assistant_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def count_assistants_by_key_id(
    db: AsyncSession,
    key_id: uuid.UUID,
) -> int:
    """Number of assistants (any status) that reference this
    provider key. Deliberately does NOT filter by ``org_id`` —
    the caller is Step 1's DAL wrapper which is invoked inside a
    per-org request context where the TenantScoped auto-filter
    from :mod:`src.app.shared.orm` already scopes the query. Belt
    is via the TenantScoped auto-filter; braces will land in Step
    6's service layer with an explicit org check."""
    stmt = select(func.count()).select_from(AiAssistant).where(AiAssistant.key_id == key_id)
    result = await db.execute(stmt)
    return int(result.scalar_one())


async def reassign_assistant_key_ids(
    db: AsyncSession,
    *,
    from_key_id: uuid.UUID,
    to_key_id: uuid.UUID,
) -> int:
    """Bulk UPDATE. Caller's service owns the transaction — this
    function stages the UPDATE and returns the row count so the
    service can log it. TenantScoped auto-filter narrows the WHERE
    to the caller's org."""
    stmt = (
        update(AiAssistant)
        .where(AiAssistant.key_id == from_key_id)
        .values(key_id=to_key_id)
    )
    result = await db.execute(stmt)
    return int(result.rowcount or 0)


__all__ = [
    "count_assistants_by_key_id",
    "get_assistant_by_id",
    "reassign_assistant_key_ids",
]
