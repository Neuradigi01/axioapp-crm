"""Data-access for the AI Assistants module.

Pure CRUD. No transactions, no permission checks, no business
logic — those live in :mod:`~core.ai_assistants.service`.

Two helpers land here at Step 5 for the BYOK reassign wiring
(``count_assistants_by_key_id`` + ``reassign_assistant_key_ids``);
Step 6 adds the full CRUD used by the operator router
(``list_assistants`` / ``get_assistant_by_id`` /
``get_assistant_by_id_no_org_filter`` / ``insert_assistant`` /
``delete_assistant`` / ``insert_instruction_audit`` +
``get_provider_key_by_id``). Optimistic-concurrency UPDATE goes
through SQLAlchemy's ``version_id_col`` machinery on ``AiAssistant``
— the service just sets ``instance.version = payload.version``
before mutating fields, and SQLAlchemy raises ``StaleDataError``
when the DB row moved on.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.ai_assistants.models import (
    AiAssistant,
    AiAssistantInstructionAudit,
    AiAssistantStatus,
)
from src.app.core.integrations.ai.models import AiProviderKey


# --- Read helpers --------------------------------------------------------


async def get_assistant_by_id(
    db: AsyncSession,
    assistant_id: uuid.UUID,
) -> AiAssistant | None:
    """RLS + TenantScoped filter ensure this only returns rows
    belonging to the caller's org. Step 6's service uses this for
    reads AFTER the timing-safe 404 pre-check has fired."""
    stmt = select(AiAssistant).where(AiAssistant.id == assistant_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_assistant_row_no_org_filter(
    db: AsyncSession,
    assistant_id: uuid.UUID,
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Raw-SQL lookup that bypasses the TenantScoped auto-filter so
    the timing-safe 404 path always issues a DB hit whether the row
    exists in another org or nowhere at all.

    Returns ``(id, org_id)`` on hit; ``None`` on miss. The service
    compares ``org_id`` against the caller's org and 404s uniformly
    on either branch.
    """
    result = await db.execute(
        text(
            "SELECT id, org_id FROM tbl_ai_assistants WHERE id = :id LIMIT 1"
        ),
        {"id": str(assistant_id)},
    )
    row = result.first()
    if row is None:
        return None
    return uuid.UUID(str(row[0])), uuid.UUID(str(row[1]))


async def list_assistants(
    db: AsyncSession,
    *,
    filter_status: AiAssistantStatus | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AiAssistant]:
    """Paginated list scoped by the TenantScoped auto-filter to the
    caller's org. Ordered by ``updated_at DESC`` so the most-recently
    edited assistant surfaces first."""
    stmt = select(AiAssistant)
    if filter_status is not None:
        stmt = stmt.where(AiAssistant.status == filter_status)
    if search:
        stmt = stmt.where(AiAssistant.name.ilike(f"%{search}%"))
    stmt = stmt.order_by(AiAssistant.updated_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_assistants(
    db: AsyncSession,
    *,
    filter_status: AiAssistantStatus | None = None,
    search: str | None = None,
) -> int:
    stmt = select(func.count()).select_from(AiAssistant)
    if filter_status is not None:
        stmt = stmt.where(AiAssistant.status == filter_status)
    if search:
        stmt = stmt.where(AiAssistant.name.ilike(f"%{search}%"))
    result = await db.execute(stmt)
    return int(result.scalar_one())


async def get_provider_key_by_id(
    db: AsyncSession,
    key_id: uuid.UUID,
) -> AiProviderKey | None:
    """Cross-org guard input. TenantScoped auto-filter narrows the
    result to keys belonging to the caller's org — service treats a
    None result as 404 (never leaks whether the key exists in
    another org)."""
    stmt = select(AiProviderKey).where(AiProviderKey.id == key_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# --- Write helpers -------------------------------------------------------


async def insert_assistant(
    db: AsyncSession,
    **values: Any,
) -> AiAssistant:
    """Stage an INSERT of :class:`AiAssistant`. Service commits."""
    row = AiAssistant(**values)
    db.add(row)
    return row


async def delete_assistant(
    db: AsyncSession,
    assistant_id: uuid.UUID,
) -> None:
    """Hard-delete. FK cascades to knowledge + chunks + audit rows;
    message_meta.assistant_id SET NULL to preserve cost history.
    Service already verified the row belongs to the caller's org."""
    row = await get_assistant_by_id(db, assistant_id)
    if row is not None:
        await db.delete(row)


async def insert_instruction_audit(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    field_name: str,
    old_value: str | None,
    new_value: str | None,
) -> AiAssistantInstructionAudit:
    row = AiAssistantInstructionAudit(
        org_id=org_id,
        assistant_id=assistant_id,
        changed_by_user_id=user_id,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
    )
    db.add(row)
    return row


async def set_assistant_status(
    db: AsyncSession,
    *,
    assistant_id: uuid.UUID,
    status: AiAssistantStatus,
) -> None:
    """Update ``status`` only. Used by the archive endpoint —
    goes through raw UPDATE so we don't collide with the
    ``version_id_col`` on the model (archive isn't user-edit).
    """
    stmt = (
        update(AiAssistant)
        .where(AiAssistant.id == assistant_id)
        .values(status=status)
    )
    await db.execute(stmt)


# --- Step-5 cross-module helpers (unchanged) -----------------------------


async def count_assistants_by_key_id(
    db: AsyncSession,
    key_id: uuid.UUID,
) -> int:
    """Number of assistants (any status) that reference this
    provider key. TenantScoped auto-filter scopes by caller's org."""
    stmt = select(func.count()).select_from(AiAssistant).where(AiAssistant.key_id == key_id)
    result = await db.execute(stmt)
    return int(result.scalar_one())


async def reassign_assistant_key_ids(
    db: AsyncSession,
    *,
    from_key_id: uuid.UUID,
    to_key_id: uuid.UUID,
) -> int:
    """Bulk UPDATE of every assistant's ``key_id`` from one key to
    another. TenantScoped auto-filter narrows to caller's org."""
    stmt = (
        update(AiAssistant)
        .where(AiAssistant.key_id == from_key_id)
        .values(key_id=to_key_id)
    )
    result = await db.execute(stmt)
    return int(result.rowcount or 0)


__all__ = [
    "count_assistants",
    "count_assistants_by_key_id",
    "delete_assistant",
    "get_assistant_by_id",
    "get_assistant_row_no_org_filter",
    "get_provider_key_by_id",
    "insert_assistant",
    "insert_instruction_audit",
    "list_assistants",
    "reassign_assistant_key_ids",
    "set_assistant_status",
]
