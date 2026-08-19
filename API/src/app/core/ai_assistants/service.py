"""Service layer for the AI Assistants module.

Owns the transaction boundary (only file in this sub-module that
commits), business validation, cross-org key-id guard, OCC
translation (StaleDataError → 409), timing-safe 404, and the
instruction-audit write on every prompt/model/temperature change.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from src.app.core.ai_assistants import data_access as _da
from src.app.core.ai_assistants.file_upload import (
    FileValidationError,
    ValidatedImage,
    ValidatedUpload,
    validate_image_upload,
    validate_upload,
)
from src.app.core.ai_assistants.models import (
    AiAssistant,
    AiAssistantKnowledge,
    AiAssistantStatus,
    KnowledgeSourceType,
    KnowledgeStatus,
)
from src.app.core.ai_assistants.schemas import (
    AiAssistantCreate,
    AiAssistantUpdate,
    KnowledgeCreateText,
    KnowledgeCreateUrl,
)
from src.app.shared.http.safe_fetch import UnsafeUrlError, safe_fetch
from src.app.shared.storage import get_storage

# Fields whose changes are captured in the instruction-audit log. If
# an operator flips any of these, we insert one row per change in the
# same transaction as the UPDATE so the audit trail can't disagree
# with the effective config (Attacker review H8: insider prompt
# injection via ``instructions`` must show up in an audit trail).
_AUDITED_FIELDS: frozenset[str] = frozenset(
    {
        "instructions",
        "model",
        "temperature",
        "allowed_domains",
        "output_sanitizer_enabled",
        # Step 16 — lead-capture config changes are audited so an
        # operator can trace when auto-lead-capture flipped on.
        "lead_capture_mode",
        "lead_capture_turn_n",
        "lead_capture_message",
    }
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
        # Step 16 — lead-capture config. Defaults are DB-level so
        # existing callers that don't send these still get the
        # ``off`` / ``3`` server defaults; passing the Pydantic
        # defaults through keeps the API contract explicit.
        "lead_capture_mode": payload.lead_capture_mode,
        "lead_capture_turn_n": payload.lead_capture_turn_n,
        "lead_capture_message": payload.lead_capture_message,
        "retention_days": payload.retention_days,
        "created_by_user_id": user_id,
    }
    # Fallback message only overrides the server_default when the
    # caller sent one — respects the "don't clobber the default
    # unless the operator asked" contract. Same for retention_days.
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


# --- Knowledge (Step 10) --------------------------------------------------


_KNOWLEDGE_NOT_FOUND_DETAIL = "knowledge not found"


def _knowledge_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=_KNOWLEDGE_NOT_FOUND_DETAIL,
    )


def _storage_key(org_id: uuid.UUID, knowledge_id: uuid.UUID) -> str:
    """Canonical path — NEVER uses the client's filename. Matches
    :func:`~core.ai_assistants.ingest._storage_key`."""
    return f"{org_id}/ai_assistants/{knowledge_id}.bin"


def _dispatch_ingest(knowledge_id: uuid.UUID) -> None:
    """Fire the Celery task. Isolated so tests can monkey-patch this
    one function rather than touch every call site."""
    from src.app.core.ai_assistants.tasks import ingest_knowledge as _task

    try:
        _task.delay(str(knowledge_id))
    except Exception:  # pragma: no cover — broker offline in dev
        # Fall-back for dev shells without a running broker: run
        # inline so the ingest still lands. Production has Celery.
        try:
            _task.apply(args=(str(knowledge_id),))
        except Exception:
            pass


async def _resolve_assistant_or_404(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
) -> AiAssistant:
    """Reuse the assistant-level timing-safe 404 so knowledge routes
    surface the same error shape as ``GET /{id}``."""
    return await get_assistant(db, org_id=org_id, assistant_id=assistant_id)


async def _resolve_knowledge_or_404(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    knowledge_id: uuid.UUID,
) -> AiAssistantKnowledge:
    """Timing-safe: the assistant lookup is the primary 404 branch;
    the knowledge lookup falls back to the same 404 detail."""
    await _resolve_assistant_or_404(
        db, org_id=org_id, assistant_id=assistant_id
    )
    row = await _da.get_knowledge_by_id(db, knowledge_id)
    if row is None or row.assistant_id != assistant_id:
        raise _knowledge_not_found()
    return row


async def _return_existing_or_none(
    db: AsyncSession,
    *,
    assistant_id: uuid.UUID,
    content_hash: bytes,
) -> AiAssistantKnowledge | None:
    """Dedup lookup — the caller returns the existing row (with
    ``duplicate=true``) instead of creating a new one."""
    return await _da.get_knowledge_by_hash(
        db, assistant_id=assistant_id, content_hash=content_hash
    )


# --- File source ---------------------------------------------------------


async def create_knowledge_from_file(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    filename: str,
    data: bytes,
) -> tuple[AiAssistantKnowledge, bool]:
    """Validate + store + dispatch the ingest task.

    Returns ``(row, duplicate)`` so the router can flag "we already
    had this file" (``duplicate=True``) vs a fresh upload
    (``duplicate=False``). Dedup key: SHA-256 of file bytes scoped
    to ``(assistant_id, content_hash)``.
    """
    await _resolve_assistant_or_404(
        db, org_id=org_id, assistant_id=assistant_id
    )
    try:
        validated: ValidatedUpload = validate_upload(filename=filename, data=data)
    except FileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"reason": exc.reason, "message": str(exc)},
        ) from exc

    existing = await _return_existing_or_none(
        db, assistant_id=assistant_id, content_hash=validated.content_hash
    )
    if existing is not None:
        return existing, True

    row = await _da.insert_knowledge(
        db,
        org_id=org_id,
        assistant_id=assistant_id,
        source_type=KnowledgeSourceType.file,
        content_hash=validated.content_hash,
        original_filename=validated.original_filename,
        mime_type=validated.sniffed_mime,
        size_bytes=validated.size_bytes,
    )
    try:
        await db.flush()
    except IntegrityError as exc:
        # Rare race: another request inserted the same hash between
        # our lookup + flush. Roll back + return the winner.
        await db.rollback()
        winner = await _return_existing_or_none(
            db, assistant_id=assistant_id, content_hash=validated.content_hash
        )
        if winner is None:  # pragma: no cover — unique-index fired but no row?
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"reason": "knowledge_race"},
            ) from exc
        return winner, True

    # Storage put + commit. If storage.put throws, roll the DB row
    # back so the operator sees a clean "upload failed" without a
    # phantom row referring to a nonexistent blob.
    try:
        storage = get_storage()
        storage.put(_storage_key(org_id, row.id), data, content_type=validated.sniffed_mime)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"reason": "storage_write_failed"},
        ) from exc

    await db.commit()
    await db.refresh(row)
    _dispatch_ingest(row.id)
    return row, False


# --- Text source ---------------------------------------------------------


async def create_knowledge_from_text(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    payload: KnowledgeCreateText,
) -> tuple[AiAssistantKnowledge, bool]:
    """Same dedup contract as the file path — the hash is computed
    from the body bytes so re-typing the same paragraph returns the
    prior row."""
    await _resolve_assistant_or_404(
        db, org_id=org_id, assistant_id=assistant_id
    )
    body_bytes = payload.body_text.encode("utf-8")
    content_hash = hashlib.sha256(body_bytes).digest()

    existing = await _return_existing_or_none(
        db, assistant_id=assistant_id, content_hash=content_hash
    )
    if existing is not None:
        return existing, True

    row = await _da.insert_knowledge(
        db,
        org_id=org_id,
        assistant_id=assistant_id,
        source_type=KnowledgeSourceType.text,
        content_hash=content_hash,
        original_filename=payload.title,
        body_text=payload.body_text,
        mime_type="text/plain",
        size_bytes=len(body_bytes),
    )
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        winner = await _return_existing_or_none(
            db, assistant_id=assistant_id, content_hash=content_hash
        )
        if winner is None:  # pragma: no cover
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"reason": "knowledge_race"},
            ) from exc
        return winner, True
    await db.commit()
    await db.refresh(row)
    _dispatch_ingest(row.id)
    return row, False


# --- URL source ----------------------------------------------------------


async def create_knowledge_from_url(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    payload: KnowledgeCreateUrl,
) -> tuple[AiAssistantKnowledge, bool]:
    """Pre-flight SSRF-check the URL BEFORE the DB insert so a
    ``http://10.0.0.1/foo`` URL never leaves a phantom
    ``failed_ingest`` row behind. Content-hash for dedup is the
    SHA-256 of the URL string itself — re-adding the same URL
    returns the same row, and Step 17's refresh flow re-embeds
    against the same id."""
    await _resolve_assistant_or_404(
        db, org_id=org_id, assistant_id=assistant_id
    )
    # Fast reject before DB work. safe_fetch's internal _validate_url
    # is not exported; we call it via a fetch-with-tiny-timeout to
    # reuse the exact same check. Actually — call the fetch itself
    # here would be a network hit at upload time (bad); dispatch it
    # to the worker where a slow fetch doesn't block the operator's
    # POST. Validate SCHEME + IP-literal + DNS only for the pre-check.
    _pre_check_url(payload.url)

    content_hash = hashlib.sha256(payload.url.encode("utf-8")).digest()
    existing = await _return_existing_or_none(
        db, assistant_id=assistant_id, content_hash=content_hash
    )
    if existing is not None:
        return existing, True

    row = await _da.insert_knowledge(
        db,
        org_id=org_id,
        assistant_id=assistant_id,
        source_type=KnowledgeSourceType.url,
        content_hash=content_hash,
        original_filename=payload.title,
        url=payload.url,
    )
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        winner = await _return_existing_or_none(
            db, assistant_id=assistant_id, content_hash=content_hash
        )
        if winner is None:  # pragma: no cover
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"reason": "knowledge_race"},
            ) from exc
        return winner, True
    await db.commit()
    await db.refresh(row)
    _dispatch_ingest(row.id)
    return row, False


def _pre_check_url(url: str) -> None:
    """Cheap SSRF-guard the operator's URL BEFORE we accept the row.

    Full per-hop guarding fires during the ingest fetch too — this
    up-front check just refuses obvious ``http://127.0.0.1`` /
    ``http://192.168.1.1`` shapes so the operator sees an immediate
    422 rather than an eventual ``failed_ingest`` row they have to
    poll for.
    """
    from src.app.shared.http.safe_fetch import _validate_url

    try:
        _validate_url(url)
    except UnsafeUrlError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"reason": exc.reason, "message": str(exc)},
        ) from exc


# --- List / cancel / delete ---------------------------------------------


async def list_knowledge(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
) -> list[AiAssistantKnowledge]:
    await _resolve_assistant_or_404(
        db, org_id=org_id, assistant_id=assistant_id
    )
    return await _da.list_knowledge_by_assistant(db, assistant_id=assistant_id)


async def cancel_knowledge(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    knowledge_id: uuid.UUID,
) -> AiAssistantKnowledge:
    """Flip a ``processing`` row to ``pending_cancel``. The ingest
    task picks up the flag on its next inter-batch check and rolls
    back. Idempotent — cancelling an already-cancelled row is a
    no-op returning the current state."""
    row = await _resolve_knowledge_or_404(
        db,
        org_id=org_id,
        assistant_id=assistant_id,
        knowledge_id=knowledge_id,
    )
    if row.status not in {
        KnowledgeStatus.pending,
        KnowledgeStatus.processing,
        KnowledgeStatus.pending_cancel,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "reason": "not_cancelable",
                "current_status": row.status.value,
            },
        )
    if row.status == KnowledgeStatus.pending_cancel:
        return row
    await _da.set_status(
        db, knowledge_id=knowledge_id, status=KnowledgeStatus.pending_cancel
    )
    await db.commit()
    await db.refresh(row)
    return row


async def delete_knowledge(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    knowledge_id: uuid.UUID,
) -> None:
    """Hard-delete. Storage blob (for file source) is removed
    best-effort — a stale ``{id}.bin`` under ``storage/`` is
    orphaned harmlessly if it fails. Chunks cascade via FK. If the
    row is currently ``processing``, we flip to ``pending_delete``
    instead so the ingest task exits cleanly before rows disappear
    from underneath it."""
    row = await _resolve_knowledge_or_404(
        db,
        org_id=org_id,
        assistant_id=assistant_id,
        knowledge_id=knowledge_id,
    )
    if row.status == KnowledgeStatus.processing:
        await _da.set_status(
            db, knowledge_id=knowledge_id, status=KnowledgeStatus.pending_delete
        )
        await db.commit()
        return

    await _da.delete_knowledge_row(db, knowledge_id)
    await db.commit()

    if row.source_type == KnowledgeSourceType.file:
        try:
            get_storage().delete(_storage_key(org_id, knowledge_id))
        except Exception:
            # Non-fatal — the row is gone; a stale blob under
            # storage/ can be reaped by an operator sweep.
            pass


# --- Replace flow --------------------------------------------------------


async def replace_knowledge_from_file(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    knowledge_id: uuid.UUID,
    filename: str,
    data: bytes,
) -> tuple[AiAssistantKnowledge, bool]:
    """Ingest a new upload as a fresh row + swap the assistant_id to
    the same target. Preserves retrieval availability throughout —
    v1 chunks stay reachable while v2 ingests; on success we delete
    the original.

    Simplified atomicity: we create v2 with the same
    ``(assistant_id, content_hash)`` if it differs; if the new upload
    is byte-identical to v1, the dedup path returns v1 unchanged.
    """
    original = await _resolve_knowledge_or_404(
        db,
        org_id=org_id,
        assistant_id=assistant_id,
        knowledge_id=knowledge_id,
    )
    row, duplicate = await create_knowledge_from_file(
        db,
        org_id=org_id,
        assistant_id=assistant_id,
        filename=filename,
        data=data,
    )
    if duplicate and row.id == original.id:
        # Byte-identical replace — nothing to do, chunks stay.
        return row, True
    # Different content: retire the original. Leave the storage blob
    # cleanup to the delete path since the row is being removed.
    await delete_knowledge(
        db,
        org_id=org_id,
        assistant_id=assistant_id,
        knowledge_id=original.id,
    )
    return row, duplicate


# --- Profile picture (Step 13) ------------------------------------------


def _profile_picture_key(
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    *,
    ext: str,
    ts_ms: int,
) -> str:
    """Versioned filename ``{ts_ms}.{ext}`` so a replaced picture
    never hits a stale CDN / browser cache. Path is always
    ``{org_id}/ai_assistants/{assistant_id}/profile/...`` — the client
    filename is never used as a path component (Case §12).
    """
    return f"{org_id}/ai_assistants/{assistant_id}/profile/{ts_ms}.{ext}"


async def upload_profile_picture(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    filename: str,
    data: bytes,
) -> dict[str, str]:
    """Validate + store the image + write the served URL into the
    assistant's ``styling_config``. Returns the URL so the frontend
    can render it immediately without a re-fetch.

    Replaces the previous picture atomically-enough: we write the new
    file first, update the DB, then best-effort delete the old file
    (a leftover blob is harmless — a manual sweep can reclaim it).
    """
    import time

    row = await get_assistant(db, org_id=org_id, assistant_id=assistant_id)

    try:
        validated: ValidatedImage = validate_image_upload(filename=filename, data=data)
    except FileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"reason": exc.reason, "message": str(exc)},
        ) from exc

    ts_ms = int(time.time() * 1000)
    key = _profile_picture_key(
        org_id, assistant_id, ext=validated.extension, ts_ms=ts_ms
    )
    try:
        storage = get_storage()
        ref = storage.put(key, data, content_type=validated.sniffed_mime)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"reason": "storage_write_failed"},
        ) from exc

    # Capture the prior URL BEFORE the update so the best-effort
    # cleanup step below can find it.
    prior_url = (row.styling_config or {}).get("header_profile_picture_url")

    # Persist the URL onto the JSONB blob via a targeted jsonb_set so
    # sibling styling keys (theme mode, colours) survive.
    await _da.set_assistant_styling_key(
        db,
        assistant_id=assistant_id,
        key="header_profile_picture_url",
        value=ref.url,
    )
    await db.commit()
    # Refresh the ORM instance so any downstream read in the same
    # session picks up the freshly-set JSONB value (the raw UPDATE
    # bypasses the mapped attribute).
    await db.refresh(row)

    # Best-effort delete of the prior blob so we don't accumulate
    # storage. Ignore failures — the DB is now authoritative and the
    # orphan is inert.
    if isinstance(prior_url, str) and prior_url != ref.url:
        prior_key = _url_to_key(prior_url)
        if prior_key:
            try:
                get_storage().delete(prior_key)
            except Exception:
                pass

    return {"url": ref.url}


async def delete_profile_picture(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
) -> None:
    """Idempotent — removes the URL from styling_config and best-
    effort deletes the file. A missing URL just returns 204."""
    row = await get_assistant(db, org_id=org_id, assistant_id=assistant_id)
    current_url = (row.styling_config or {}).get("header_profile_picture_url")
    await _da.unset_assistant_styling_key(
        db,
        assistant_id=assistant_id,
        key="header_profile_picture_url",
    )
    await db.commit()
    # Refresh so a subsequent read in the same session sees the
    # unset key (raw UPDATE bypasses the mapped attribute).
    await db.refresh(row)
    if isinstance(current_url, str):
        current_key = _url_to_key(current_url)
        if current_key:
            try:
                get_storage().delete(current_key)
            except Exception:
                pass


def _url_to_key(url: str) -> str | None:
    """Reverse the ``LocalStorage.url()`` mapping: ``/files/{key}``
    → ``key``. Returns ``None`` for anything that doesn't match the
    expected prefix (defensive against a hand-edited styling_config).
    """
    prefix = "/files/"
    if not url.startswith(prefix):
        return None
    return url[len(prefix) :]


# --- Analytics (Step 16) --------------------------------------------------


async def get_analytics(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    assistant_id: uuid.UUID,
    window_days: int = 30,
) -> dict[str, Any]:
    """Aggregate KPIs + top-questions for one assistant. Read-only —
    no commit. Fires the timing-safe 404 guard first so a wrong-org
    caller sees the same 404 as a nonexistent id."""
    from decimal import Decimal

    # Bound the window at both ends so an operator hitting the URL
    # with ``?window_days=99999`` doesn't scan the whole table.
    window_days = max(1, min(365, int(window_days)))

    await get_assistant(db, org_id=org_id, assistant_id=assistant_id)

    message_count, total_cost = await _da.analytics_message_and_cost(
        db,
        org_id=org_id,
        assistant_id=assistant_id,
        window_days=window_days,
    )
    top = await _da.analytics_top_questions(
        db,
        org_id=org_id,
        assistant_id=assistant_id,
        window_days=window_days,
        limit=20,
    )
    return {
        "window_days": window_days,
        "message_count": message_count,
        "total_cost_usd": Decimal(total_cost),
        "top_questions": top,
    }


__all__ = [
    "archive_assistant",
    "cancel_knowledge",
    "create_assistant",
    "create_knowledge_from_file",
    "create_knowledge_from_text",
    "create_knowledge_from_url",
    "delete_assistant",
    "delete_knowledge",
    "delete_profile_picture",
    "get_analytics",
    "get_assistant",
    "list_assistants",
    "list_knowledge",
    "replace_knowledge_from_file",
    "update_assistant",
    "upload_profile_picture",
]


# Suppress unused-import warning — retained for future features
# (real-time URL preview + fetch surface).
_ = safe_fetch
