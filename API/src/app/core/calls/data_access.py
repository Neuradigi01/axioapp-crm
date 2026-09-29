"""Data-access layer for the call-center module.

Pure query helpers — no transactions, no audit, no business rules.
Leaf module; never imports a ``service.py``.

Three concerns mirror the service layer:

  * ``tbl_call_outcomes`` — list/get/insert/delete; caller surfaces
    409 on the ``(org_id, key)`` unique violation.
  * ``tbl_calls`` + ``tbl_call_transcripts`` — list/get/insert/delete,
    plus the one-per-call transcript lookup.
  * Analytics — three GROUP BY rollups over the
    ``[from_dt, to_dt]`` window: outcomes distribution, daily volume,
    direction split. Service composes them into the response dict.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date as Date
from typing import Any

from sqlalchemy import and_, cast, func, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Date as SADate

from src.app.core.calls.models import (
    Call,
    CallDirection,
    CallOutcome,
    CallTranscript,
)
from src.app.core.contacts.models import Contact
from src.app.core.users.models import User, UserInfo
from src.app.shared.db.pagination import paginate

# --- Outcomes -----------------------------------------------------------


async def list_outcomes_query(session: AsyncSession) -> list[CallOutcome]:
    """All call outcomes for this org, ordered by display position then
    label."""
    stmt = select(CallOutcome).order_by(CallOutcome.display_order.asc(), CallOutcome.label.asc())
    return list((await session.execute(stmt)).scalars().all())


async def get_outcome_by_id(session: AsyncSession, outcome_id: uuid.UUID) -> CallOutcome | None:
    """Single-row read by PK. ``None`` on miss."""
    result = await session.execute(select(CallOutcome).where(CallOutcome.id == outcome_id))
    return result.scalar_one_or_none()


# --- Calls --------------------------------------------------------------


async def list_calls_query(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID | None = None,
    direction: CallDirection | None = None,
    assigned_to_id: uuid.UUID | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[Call], int]:
    """Filtered paginated list, ordered by started_at desc (created_at
    as tiebreaker)."""
    base = select(Call)
    filters: list[Any] = []
    if contact_id is not None:
        filters.append(Call.contact_id == contact_id)
    if direction is not None:
        filters.append(Call.direction == direction)
    if assigned_to_id is not None:
        filters.append(Call.assigned_to_id == assigned_to_id)
    if filters:
        base = base.where(and_(*filters))
    base = base.order_by(Call.started_at.desc(), Call.created_at.desc())
    return await paginate(session, base, page=page, size=size)


async def get_call_by_id(session: AsyncSession, call_id: uuid.UUID) -> Call | None:
    """Single-row read by PK."""
    result = await session.execute(select(Call).where(Call.id == call_id))
    return result.scalar_one_or_none()


# --- Denormalised name lookups for the list view -----------------------
#
# Kept in the calls DAL rather than reaching into another module's DAL
# because these are plain single-column reads with no business rules —
# the layering rule permits DAL-to-DAL joins for lookup helpers of this
# shape. Both helpers return empty dicts for empty input so the caller
# can pass them unconditionally.


async def get_contact_names_bulk(
    session: AsyncSession,
    *,
    contact_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """Resolve contact UUIDs to display names in one query.

    Not org-scoped: the tenant filter on ``TenantScoped`` already
    constrains the read to the calling org's rows, and a call row can
    only reference contacts owned by the same org (FK + RLS)."""
    ids = list({cid for cid in contact_ids if cid is not None})
    if not ids:
        return {}
    rows = (
        await session.execute(select(Contact.id, Contact.full_name).where(Contact.id.in_(ids)))
    ).all()
    return {cid: name for cid, name in rows}


async def get_user_display_names_bulk(
    session: AsyncSession,
    *,
    user_uuids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """Resolve user UUIDs (``User.legacy_uuid``) to display names.

    Deliberately NOT filtered by ``is_active`` so historical rows still
    render the original rep's name even if that rep has since been
    removed from the org. Falls back to email when both name parts are
    blank; falls back to the empty string when the row can't be found
    (caller renders "—")."""
    uuids = list({u for u in user_uuids if u is not None})
    if not uuids:
        return {}
    rows = (
        await session.execute(
            select(
                User.legacy_uuid,
                UserInfo.first_name,
                UserInfo.last_name,
                UserInfo.email,
            )
            .join(UserInfo, UserInfo.member_id == User.id)
            .where(User.legacy_uuid.in_(uuids))
        )
    ).all()
    out: dict[uuid.UUID, str] = {}
    for user_uuid, first, last, email in rows:
        name = f"{(first or '').strip()} {(last or '').strip()}".strip()
        out[user_uuid] = name or (email or "")
    return out


# --- Transcript ---------------------------------------------------------


async def get_transcript_for_call(
    session: AsyncSession, *, call_id: uuid.UUID
) -> CallTranscript | None:
    """One transcript per call. ``None`` if the call has never had
    a transcript captured."""
    return (
        await session.execute(select(CallTranscript).where(CallTranscript.call_id == call_id))
    ).scalar_one_or_none()


# --- Analytics ----------------------------------------------------------


def _date_window(from_dt: Date, to_dt: Date):
    """Reusable ``[from_dt, to_dt]`` window expression keyed off
    ``started_at::date``."""
    started_date = cast(Call.started_at, SADate)
    return started_date, and_(started_date >= from_dt, started_date <= to_dt)


async def outcomes_distribution_query(
    session: AsyncSession, *, from_dt: Date, to_dt: Date
) -> list[Row]:
    """GROUP BY outcome with LEFT JOIN to ``tbl_call_outcomes`` so rows
    with no recorded outcome still appear (NULL key/label/color)."""
    _, window = _date_window(from_dt, to_dt)
    stmt = (
        select(
            Call.outcome_id,
            CallOutcome.key,
            CallOutcome.label,
            CallOutcome.color,
            func.count(Call.id).label("count"),
        )
        .select_from(Call)
        .join(CallOutcome, CallOutcome.id == Call.outcome_id, isouter=True)
        .where(window)
        .group_by(Call.outcome_id, CallOutcome.key, CallOutcome.label, CallOutcome.color)
        .order_by(func.count(Call.id).desc())
    )
    return list((await session.execute(stmt)).all())


async def daily_volume_query(session: AsyncSession, *, from_dt: Date, to_dt: Date) -> list[Row]:
    """GROUP BY ``started_at::date`` to produce a daily count series
    ordered ascending — direct chart input."""
    started_date, window = _date_window(from_dt, to_dt)
    stmt = (
        select(started_date.label("day"), func.count(Call.id).label("count"))
        .where(window)
        .group_by(started_date)
        .order_by(started_date.asc())
    )
    return list((await session.execute(stmt)).all())


async def direction_split_query(session: AsyncSession, *, from_dt: Date, to_dt: Date) -> list[Row]:
    """GROUP BY direction (inbound / outbound) for the same window."""
    _, window = _date_window(from_dt, to_dt)
    stmt = (
        select(Call.direction, func.count(Call.id).label("count"))
        .where(window)
        .group_by(Call.direction)
    )
    return list((await session.execute(stmt)).all())


# --- writes (caller commits) --------------------------------------------


def insert_outcome(session: AsyncSession, outcome: CallOutcome) -> None:
    """Register an already-constructed CallOutcome for INSERT."""
    session.add(outcome)


def insert_call(session: AsyncSession, call: Call) -> None:
    """Register an already-constructed Call for INSERT."""
    session.add(call)


def insert_transcript(session: AsyncSession, transcript: CallTranscript) -> None:
    """Register an already-constructed CallTranscript for INSERT."""
    session.add(transcript)


async def delete_outcome_row(session: AsyncSession, outcome: CallOutcome) -> None:
    """Mark a CallOutcome row for DELETE."""
    await session.delete(outcome)


async def delete_call_row(session: AsyncSession, call: Call) -> None:
    """Mark a Call row for DELETE."""
    await session.delete(call)


__all__ = [
    "daily_volume_query",
    "delete_call_row",
    "delete_outcome_row",
    "direction_split_query",
    "get_call_by_id",
    "get_contact_names_bulk",
    "get_outcome_by_id",
    "get_transcript_for_call",
    "get_user_display_names_bulk",
    "insert_call",
    "insert_outcome",
    "insert_transcript",
    "list_calls_query",
    "list_outcomes_query",
    "outcomes_distribution_query",
]
