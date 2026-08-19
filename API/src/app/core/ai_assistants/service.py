"""Service layer for the AI Assistants module.

Owns the transaction boundary (only file in this sub-module that
commits), business validation, cross-org key-id guard, OCC
translation (StaleDataError → 409), timing-safe 404, and the
instruction-audit write on every prompt/model/temperature change.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from src.app.core.ai_assistants import data_access as _da
from src.app.core.ai_assistants.models import AiAssistant, AiAssistantStatus
from src.app.core.ai_assistants.schemas import (
    AiAssistantCreate,
    AiAssistantUpdate,
)

# Fields whose changes are captured in the instruction-audit log. If
# an operator flips any of these, we insert one row per change in the
# same transaction as the UPDATE so the audit trail can't disagree
# with the effective config (Attacker review H8: insider prompt
# injection via ``instructions`` must show up in an audit trail).
_AUDITED_FIELDS: frozenset[str] = frozenset(
    {"instructions", "model", "temperature", "allowed_domains", "output_sanitizer_enabled"}
)

_ENTITY = "assistant"

# 404 detail is a single string identical on both branches
# (wrong-org row + nonexistent id) so timing + body match — no
# side channel that a scanner could use to enumerate ids.
_NOT_FOUND_DETAIL = "assistant not found"


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)


# --- Read paths ----------------------------------------------------------


async def list_assistants(
    db: AsyncSession,
    *,
    filter_status: AiAssistantStatus | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AiAssistant], int]:
    rows = await _da.list_assistants(
        db,
        filter_status=filter_status,
        search=search,
        limit=limit,
        offset=offset,
    )
    total = await _da.count_assistants(db, filter_status=filter_status, search=search)
    return rows, total


async def get_assistant(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
) -> AiAssistant:
    """Timing-safe 404 pattern.

    Always execute a bare-SQL lookup (no TenantScoped filter) so a
    wrong-org id and a nonexistent id both hit the DB. Then compare
    ``org_id`` in Python. On either branch, raise the SAME
    HTTPException with the SAME detail string.

    After the check, re-fetch the row through the normal ORM path
    (which the auto-filter scopes to the caller's org) to return
    the full model. This second query only happens on the happy
    path, so the timing-parity envelope holds for the 404 case.
    """
    id_org = await _da.get_assistant_row_no_org_filter(db, assistant_id)
    if id_org is None or id_org[1] != org_id:
        raise _not_found()
    row = await _da.get_assistant_by_id(db, assistant_id)
    if row is None:  # pragma: no cover — RLS + auto-filter should always hit
        raise _not_found()
    return row


# --- Write paths ---------------------------------------------------------


async def _validate_key_belongs_to_org(
    db: AsyncSession,
    *,
    key_id: uuid.UUID,
) -> None:
    """TenantScoped auto-filter on ``AiProviderKey`` scopes the
    SELECT to the caller's org — a None result means "either the key
    doesn't exist OR it belongs to another org". Both branches must
    surface as 404 (never leak existence), so we use the same
    ``_not_found()`` shape."""
    key = await _da.get_provider_key_by_id(db, key_id)
    if key is None:
        raise _not_found()


def _apply_updates(instance: AiAssistant, payload: AiAssistantUpdate) -> dict[str, tuple[Any, Any]]:
    """Apply the payload's non-None fields onto ``instance`` and
    return a diff dict ``{field: (old, new)}`` for the instruction
    audit path. Excludes ``version`` (SQLAlchemy manages it)."""
    data = payload.model_dump(exclude_unset=True, exclude={"version"})
    changes: dict[str, tuple[Any, Any]] = {}
    for field, new in data.items():
        old = getattr(instance, field)
        if old != new:
            changes[field] = (old, new)
        setattr(instance, field, new)
    return changes


async def _write_audit_for_changes(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    user_id: uuid.UUID | None,
    changes: dict[str, tuple[Any, Any]],
) -> None:
    for field, (old, new) in changes.items():
        if field not in _AUDITED_FIELDS:
            continue
        await _da.insert_instruction_audit(
            db,
            org_id=org_id,
            assistant_id=assistant_id,
            user_id=user_id,
            field_name=field,
            old_value=None if old is None else str(old),
            new_value=None if new is None else str(new),
        )


async def create_assistant(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    payload: AiAssistantCreate,
) -> AiAssistant:
    await _validate_key_belongs_to_org(db, key_id=payload.key_id)

    values: dict[str, Any] = {
        "org_id": org_id,
        "name": payload.name,
        "description": payload.description,
        "key_id": payload.key_id,
        "model": payload.model,
        "temperature": payload.temperature,
        "instructions": payload.instructions,
        "stop_keywords": list(payload.stop_keywords),
        "retry_attempts": payload.retry_attempts,
        "allowed_domains": list(payload.allowed_domains),
        "output_sanitizer_enabled": payload.output_sanitizer_enabled,
        "budget_cap_override_usd": payload.budget_cap_override_usd,
        "created_by_user_id": user_id,
    }
    # Fallback message only overrides the server_default when the
    # caller sent one — respects the "don't clobber the default
    # unless the operator asked" contract.
    if payload.fallback_message is not None:
        values["fallback_message"] = payload.fallback_message

    row = await _da.insert_assistant(db, **values)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        # Unique index on (org_id, lower(name)) — surface as 409.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "duplicate_assistant_name", "name": payload.name},
        ) from exc

    if payload.instructions is not None:
        await _da.insert_instruction_audit(
            db,
            org_id=org_id,
            assistant_id=row.id,
            user_id=user_id,
            field_name="instructions",
            old_value=None,
            new_value=payload.instructions,
        )

    await db.commit()
    await db.refresh(row)
    return row


async def update_assistant(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    assistant_id: uuid.UUID,
    payload: AiAssistantUpdate,
) -> AiAssistant:
    # Timing-safe 404 first — bypasses TenantScoped for the id
    # check so wrong-org / nonexistent look identical from outside.
    row = await get_assistant(db, org_id=org_id, assistant_id=assistant_id)

    # Cross-org key_id guard runs BEFORE the OCC check so operators
    # who forgot to bump `version` see the more actionable 404 first
    # (rather than getting a 409 that becomes 404 on retry).
    if payload.key_id is not None and payload.key_id != row.key_id:
        await _validate_key_belongs_to_org(db, key_id=payload.key_id)

    # SQLAlchemy's version_id_col machinery reads the mapped
    # `version` attribute and enforces WHERE version = :current on
    # UPDATE. Setting the attribute to the payload's version simulates
    # "I saw the row at v=N" so a stale N produces StaleDataError on
    # flush.
    if row.version != payload.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "reason": "stale_version",
                "current_version": row.version,
                "supplied_version": payload.version,
            },
        )

    changes = _apply_updates(row, payload)

    try:
        await db.flush()
    except StaleDataError as exc:
        # Racing concurrent update between the read + flush — the DB
        # row moved on. Surface as 409 (client should re-read).
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "stale_version_race"},
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "duplicate_assistant_name"},
        ) from exc

    if changes:
        await _write_audit_for_changes(
            db,
            org_id=org_id,
            assistant_id=row.id,
            user_id=user_id,
            changes=changes,
        )

    await db.commit()
    await db.refresh(row)
    return row


async def archive_assistant(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
) -> None:
    """Idempotent — flipping an already-archived row to archived is
    a no-op. Version_id_col NOT incremented (archive isn't a user
    edit; skipping the bump avoids racing operator edits)."""
    await get_assistant(db, org_id=org_id, assistant_id=assistant_id)
    await _da.set_assistant_status(
        db,
        assistant_id=assistant_id,
        status=AiAssistantStatus.archived,
    )
    await db.commit()


async def delete_assistant(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
) -> None:
    """Hard-delete. Cascades knowledge + chunks + audit rows;
    ``tbl_ai_assistant_message_meta.assistant_id`` set NULL to
    preserve cost/audit history (Case §24 in the track README)."""
    await get_assistant(db, org_id=org_id, assistant_id=assistant_id)
    await _da.delete_assistant(db, assistant_id)
    await db.commit()


__all__ = [
    "archive_assistant",
    "create_assistant",
    "delete_assistant",
    "get_assistant",
    "list_assistants",
    "update_assistant",
]
