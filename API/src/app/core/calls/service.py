"""Service layer for the call-center module.

Three concerns:

1. Calls CRUD — paginated list with filter knobs (contact_id,
   direction, assigned_to_id), single create/update/delete, and a
   transcript upsert.
2. Outcomes config — bare CRUD over `call_outcomes` (admin-only via
   `calls.outcomes.manage` at the router).
3. Analytics — three chart-ready arrays for the `from..to` window:
   outcomes distribution, daily volume, direction split.

Every mutation fires `audit.log`; creates also log an `Activity` with
`type='call'` on the linked contact (if any) so the contact timeline
shows it.
"""

from __future__ import annotations

import uuid
from datetime import date as Date
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.activities.models import ActivityType
from src.app.core.activities.service import log as activities_log
from src.app.core.calls import data_access as _da
from src.app.core.calls.models import (
    Call,
    CallDirection,
    CallOutcome,
    CallTranscript,
)
from src.app.core.calls.schemas import (
    CallCreate,
    CallOutcomeCreate,
    CallOutcomeUpdate,
    CallTranscriptUpsert,
    CallUpdate,
)
from src.app.shared.audit import log_entity_change
from src.app.shared.db.queries import ensure_found

# --- Outcomes -------------------------------------------------------------


async def list_outcomes(session: AsyncSession) -> list[CallOutcome]:
    return await _da.list_outcomes_query(session)


async def create_outcome(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: CallOutcomeCreate,
) -> CallOutcome:
    outcome = CallOutcome(
        org_id=org_id,
        key=payload.key,
        label=payload.label,
        color=payload.color,
        display_order=payload.display_order,
    )
    _da.insert_outcome(session, outcome)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"call outcome '{payload.key}' already exists for this org",
        ) from None
    await session.refresh(outcome)
    await log_entity_change(
        action="calls.outcome_created",
        entity_type="call_outcome",
        entity_id=outcome.id,
        after=_outcome_snapshot(outcome),
    )
    return outcome


async def update_outcome(
    session: AsyncSession,
    *,
    outcome_id: uuid.UUID,
    payload: CallOutcomeUpdate,
) -> CallOutcome:
    outcome = await _get_outcome(session, outcome_id)
    before = _outcome_snapshot(outcome)
    changed = False
    if payload.label is not None:
        outcome.label = payload.label
        changed = True
    if payload.color is not None:
        outcome.color = payload.color
        changed = True
    if payload.display_order is not None:
        outcome.display_order = payload.display_order
        changed = True
    if changed:
        await session.commit()
        await session.refresh(outcome)
        await log_entity_change(
            action="calls.outcome_updated",
            entity_type="call_outcome",
            entity_id=outcome.id,
            before=before,
            after=_outcome_snapshot(outcome),
        )
    return outcome


async def delete_outcome(session: AsyncSession, *, outcome_id: uuid.UUID) -> None:
    outcome = await _get_outcome(session, outcome_id)
    before = _outcome_snapshot(outcome)
    await _da.delete_outcome_row(session, outcome)
    await session.commit()
    await log_entity_change(
        action="calls.outcome_deleted",
        entity_type="call_outcome",
        entity_id=outcome_id,
        before=before,
    )


async def _get_outcome(session: AsyncSession, outcome_id: uuid.UUID) -> CallOutcome:
    return ensure_found(await _da.get_outcome_by_id(session, outcome_id), entity="call outcome")


# --- Calls CRUD ------------------------------------------------------------


async def list_calls(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID | None = None,
    direction: CallDirection | None = None,
    assigned_to_id: uuid.UUID | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Call], int, dict[uuid.UUID, str], dict[uuid.UUID, str]]:
    """Paginated calls list plus (contact_id → name) and
    (created_by_id → name) maps for the returned page.

    The name maps are batched — one query per map, regardless of page
    size — so the router can render "Logged by Alice" / contact-name
    cells without an N+1 fetch on the frontend."""
    rows, total = await _da.list_calls_query(
        session,
        contact_id=contact_id,
        direction=direction,
        assigned_to_id=assigned_to_id,
        page=page,
        size=size,
    )
    contact_names = await _da.get_contact_names_bulk(
        session, contact_ids=[r.contact_id for r in rows if r.contact_id]
    )
    creator_names = await _da.get_user_display_names_bulk(
        session, user_uuids=[r.created_by_id for r in rows if r.created_by_id]
    )
    return rows, total, contact_names, creator_names


async def get_call(session: AsyncSession, call_id: uuid.UUID) -> Call:
    return ensure_found(await _da.get_call_by_id(session, call_id), entity="call")


async def create_call(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: CallCreate,
) -> Call:
    call = Call(
        org_id=org_id,
        contact_id=payload.contact_id,
        direction=payload.direction,
        started_at=payload.started_at,
        duration_sec=payload.duration_sec,
        outcome_id=payload.outcome_id,
        notes=payload.notes,
        recording_url=payload.recording_url,
        assigned_to_id=payload.assigned_to_id,
        # Stamp the caller so the Call Logs table can render "Logged by
        # <rep>". Bypassable only by direct DB write — every code path
        # into ``create_call`` comes from the authenticated router.
        created_by_id=user_id,
        custom_data=payload.custom_data,
    )
    _da.insert_call(session, call)
    await session.commit()
    await session.refresh(call)

    await log_entity_change(
        action="calls.created",
        entity_type="call",
        entity_id=call.id,
        after=_call_snapshot(call),
    )
    if call.contact_id is not None:
        await activities_log(
            entity_type="contact",
            entity_id=call.contact_id,
            type=ActivityType.call,
            payload={
                "call_id": str(call.id),
                "direction": call.direction.value,
                "duration_sec": call.duration_sec,
            },
            user_id=user_id,
            org_id=org_id,
        )
    return call


async def update_call(
    session: AsyncSession,
    *,
    call_id: uuid.UUID,
    payload: CallUpdate,
) -> Call:
    call = await get_call(session, call_id)
    before = _call_snapshot(call)
    changed = False
    if payload.contact_id is not None:
        call.contact_id = payload.contact_id
        changed = True
    if payload.duration_sec is not None:
        call.duration_sec = payload.duration_sec
        changed = True
    if payload.outcome_id is not None:
        call.outcome_id = payload.outcome_id
        changed = True
    if payload.notes is not None:
        call.notes = payload.notes
        changed = True
    if payload.recording_url is not None:
        call.recording_url = payload.recording_url
        changed = True
    if payload.assigned_to_id is not None:
        call.assigned_to_id = payload.assigned_to_id
        changed = True
    if payload.custom_data is not None:
        call.custom_data = payload.custom_data
        changed = True
    if changed:
        await session.commit()
        await session.refresh(call)
        await log_entity_change(
            action="calls.updated",
            entity_type="call",
            entity_id=call.id,
            before=before,
            after=_call_snapshot(call),
        )
    return call


async def delete_call(session: AsyncSession, *, call_id: uuid.UUID) -> None:
    call = await get_call(session, call_id)
    before = _call_snapshot(call)
    await _da.delete_call_row(session, call)
    await session.commit()
    await log_entity_change(
        action="calls.deleted",
        entity_type="call",
        entity_id=call_id,
        before=before,
    )


# --- Recording upload ----------------------------------------------------
#
# Recordings are attached AFTER the call is logged — the rep drag-drops an
# audio file into the Log Call modal. We store the raw file on disk under
# `./storage/{org_id}/call_recordings/{uuid}.{ext}` and persist only the
# relative path on the row. Playback is a separate streaming endpoint so
# the file bytes are auth-gated (never a public URL).


_ALLOWED_RECORDING_EXTS: frozenset[str] = frozenset({".mp3", ".m4a", ".ogg", ".wav"})
_MAX_RECORDING_BYTES: int = 30 * 1024 * 1024  # 30 MB


async def attach_recording_file(
    session: AsyncSession,
    *,
    call_id: uuid.UUID,
    filename: str,
    data: bytes,
    content_type: str | None,
) -> Call:
    """Save an uploaded audio file, update ``tbl_calls.recording_file_path``,
    and return the mutated Call. Validates the extension + size cap up
    front so oversized uploads fail cheaply."""
    from pathlib import PurePosixPath

    from src.app.shared.storage import get_storage

    call = await get_call(session, call_id)

    if len(data) > _MAX_RECORDING_BYTES:
        raise HTTPException(
            # `HTTP_413_CONTENT_TOO_LARGE` was renamed from
            # `HTTP_413_REQUEST_ENTITY_TOO_LARGE` in Starlette; use the
            # numeric code directly so we don't depend on either name.
            status_code=413,
            detail=(
                f"Recording too large ({len(data) // (1024 * 1024)} MB). "
                f"Maximum: 30 MB."
            ),
        )
    ext = PurePosixPath(filename or "").suffix.lower()
    if ext not in _ALLOWED_RECORDING_EXTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Unsupported audio format. Allowed: "
                + ", ".join(sorted(_ALLOWED_RECORDING_EXTS))
                + " (video formats like .mp4 are not accepted)."
            ),
        )

    before = _call_snapshot(call)
    file_id = uuid.uuid4()
    storage_path = f"{call.org_id}/call_recordings/{file_id}{ext}"
    get_storage().put(storage_path, data, content_type=content_type)

    call.recording_file_path = storage_path
    await session.commit()
    await session.refresh(call)

    await log_entity_change(
        action="calls.recording_uploaded",
        entity_type="call",
        entity_id=call_id,
        before=before,
        after=_call_snapshot(call),
    )
    return call


async def read_recording_file(
    session: AsyncSession, *, call_id: uuid.UUID
) -> tuple[bytes, str]:
    """Load an uploaded recording's bytes for streaming playback.

    Returns ``(data, content_type)``. Raises 404 when the call has no
    uploaded recording (the client should fall back to
    ``recording_url``).
    """
    from pathlib import Path

    call = await get_call(session, call_id)
    if not call.recording_file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No recording uploaded for this call.",
        )

    # Root matches ``LocalStorage.__init__`` default.
    root = Path("./storage").resolve()
    target = (root / call.recording_file_path).resolve()
    if not target.is_file():
        # Path in DB but file missing on disk — corrupted state.
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Recording file is no longer on disk.",
        )
    # Guardrail: prevent path traversal in case a bad row landed in DB.
    if not str(target).startswith(str(root)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid recording path.",
        )

    data = target.read_bytes()
    content_type = _content_type_for(call.recording_file_path)
    return data, content_type


def _content_type_for(path: str) -> str:
    """Map file extension → audio MIME type for the streaming Response."""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return {
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "ogg": "audio/ogg",
        "wav": "audio/wav",
    }.get(ext, "application/octet-stream")


# --- Transcript -----------------------------------------------------------


async def get_transcript(session: AsyncSession, *, call_id: uuid.UUID) -> CallTranscript | None:
    return await _da.get_transcript_for_call(session, call_id=call_id)


async def upsert_transcript(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    call_id: uuid.UUID,
    payload: CallTranscriptUpsert,
) -> CallTranscript:
    """One transcript per call. Replaces an existing row in place."""
    await get_call(session, call_id)  # 404s if no such call

    existing = await get_transcript(session, call_id=call_id)
    before = (
        {"text": existing.text, "language": existing.language} if existing is not None else None
    )
    if existing is None:
        transcript = CallTranscript(
            org_id=org_id,
            call_id=call_id,
            text=payload.text,
            language=payload.language,
        )
        _da.insert_transcript(session, transcript)
    else:
        existing.text = payload.text
        existing.language = payload.language
        transcript = existing
    await session.commit()
    await session.refresh(transcript)
    await audit.log(
        "calls.transcript_upserted",
        entity_type="call",
        entity_id=call_id,
        before=before,
        after={"text": transcript.text[:160], "language": transcript.language},
    )
    return transcript


# --- Analytics ------------------------------------------------------------


async def analytics(
    session: AsyncSession,
    *,
    from_dt: Date,
    to_dt: Date,
) -> dict[str, Any]:
    """Three chart-ready arrays over `[from_dt, to_dt]` inclusive."""
    if to_dt < from_dt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`to` must be on or after `from`",
        )

    outcomes_rows = [
        {
            "outcome_id": r.outcome_id,
            "outcome_key": r.key,
            "outcome_label": r.label,
            "outcome_color": r.color,
            "count": int(r.count),
        }
        for r in await _da.outcomes_distribution_query(session, from_dt=from_dt, to_dt=to_dt)
    ]

    daily_rows = [
        {"day": r.day, "count": int(r.count)}
        for r in await _da.daily_volume_query(session, from_dt=from_dt, to_dt=to_dt)
    ]

    direction_rows = [
        {"direction": r.direction, "count": int(r.count)}
        for r in await _da.direction_split_query(session, from_dt=from_dt, to_dt=to_dt)
    ]

    return {
        "from": from_dt,
        "to": to_dt,
        "outcomes": outcomes_rows,
        "daily": daily_rows,
        "direction": direction_rows,
    }


# --- snapshots -------------------------------------------------------------


def _outcome_snapshot(o: CallOutcome) -> dict[str, Any]:
    return {
        "id": str(o.id),
        "key": o.key,
        "label": o.label,
        "color": o.color,
        "display_order": o.display_order,
    }


def _call_snapshot(c: Call) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "contact_id": str(c.contact_id) if c.contact_id else None,
        "direction": c.direction.value,
        "started_at": c.started_at.isoformat(),
        "duration_sec": c.duration_sec,
        "outcome_id": str(c.outcome_id) if c.outcome_id else None,
        "assigned_to_id": str(c.assigned_to_id) if c.assigned_to_id else None,
        "created_by_id": str(c.created_by_id) if c.created_by_id else None,
        "has_recording_file": bool(c.recording_file_path),
    }


__all__ = [
    "analytics",
    "attach_recording_file",
    "create_call",
    "create_outcome",
    "read_recording_file",
    "delete_call",
    "delete_outcome",
    "get_call",
    "get_transcript",
    "list_calls",
    "list_outcomes",
    "update_call",
    "update_outcome",
    "upsert_transcript",
]
