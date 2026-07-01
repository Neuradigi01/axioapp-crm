"""High-level orchestrator: reconcile ONE appointment's state with
the assignee's Google Calendar. Called from the Step-4 Celery task
once per appointment mutation (create / update / delete /
reassignment) and from the reconciliation beat sweep.

Layered per manager spec: service.py is the only file that touches
transactions. This module commits per-appointment (short txn) so a
long-running sweep can be interrupted mid-batch without losing prior
progress.

Decision tree (spec's decision diagram):

.. code::

    Fetch appointment + fetch user's token row
    ├─ Token row missing / status != 'active' → skip, no-op
    ├─ Appointment gone (deleted) OR unassigned →
    │    if stored event_id → DELETE + null out
    │    else               → skip
    ├─ Appointment exists + no event_id → CREATE + store id + etag
    └─ Appointment exists + event_id     → PATCH + refresh etag

Reassignment special case (assigned_to_id changed to a different
user): the sync task explicitly dispatches TWO calls — one with the
OLD assignee's user_id (deletes their event), one with the NEW
assignee's user_id (creates fresh). We DON'T sniff for reassignment
inside :func:`sync_appointment` — the task layer knows both old +
new because it fires the hooks. That keeps this function's contract
crisp: "reconcile ``appointment`` against ``user_id``'s calendar".

The API client is stateless; retry / backoff live one layer up in
the Celery task (autoretry_for=GoogleCalendarRateLimited).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.appointments.models import Appointment, AppointmentStatus
from src.app.core.contacts.models import Contact
from src.app.core.integrations.google_calendar import (
    api_client as _client,
    data_access as _da,
)
from src.app.core.integrations.google_calendar.exceptions import (
    GoogleCalendarConcurrencyConflict,
    GoogleCalendarError,
    GoogleCalendarEventGone,
    GoogleCalendarTokenExpired,
)
from src.app.core.tenants.models import Organization

logger = logging.getLogger(__name__)


# --- Public API --------------------------------------------------------


async def sync_appointment(
    session: AsyncSession,
    *,
    appointment_id: uuid.UUID,
    user_id: int,
    http_client: httpx.AsyncClient | None = None,
) -> str:
    """Reconcile one appointment with ``user_id``'s Google Calendar.

    Returns a summary string: ``'created'`` / ``'updated'`` /
    ``'deleted'`` / ``'skipped'``. Never raises for expected states
    (missing appointment, missing token row, unassigned appointment)
    — those become ``'skipped'``. Raises :class:`GoogleCalendarError`
    (or subclasses) on Google-side failures the caller should log +
    react to (typically via the Celery task's retry / backoff)."""
    appointment = await _load_appointment(session, appointment_id)
    token = await _da.get_active_token_for_user(
        session, org_id=_org_id_of(appointment, user_id), user_id=user_id
    )

    if token is None:
        logger.info(
            "google_calendar.sync_appointment skipped_no_token "
            "appointment=%s user=%d",
            appointment_id,
            user_id,
        )
        return "skipped"

    # --- Delete-path branches -------------------------------------------
    # Appointment gone OR unassigned-relative-to-this-user OR cancelled.
    is_deleted = appointment is None
    assignee_login_id = (
        await _resolve_login_id(session, appointment.assigned_to_id)
        if appointment is not None
        else None
    )
    is_cancelled_or_unassigned = (
        appointment is not None
        and (
            appointment.status == AppointmentStatus.cancelled
            or appointment.assigned_to_id is None
            or assignee_login_id != user_id
        )
    )

    if is_deleted or is_cancelled_or_unassigned:
        # If we ever synced this appointment to this calendar, tear it
        # down. Otherwise no-op.
        if appointment is not None and appointment.google_calendar_event_id:
            await _delete_event_and_null_out(
                session,
                appointment=appointment,
                token=token,
                http_client=http_client,
            )
            return "deleted"
        return "skipped"

    # --- Create / update path ------------------------------------------
    calendar_id = await _ensure_primary_calendar_id(
        session, token=token, http_client=http_client
    )
    contact = await _load_contact(session, appointment.contact_id)
    org = await _load_org(session, appointment.org_id)
    event_body = _build_event_body(
        appointment=appointment,
        contact=contact,
        org_timezone=(org.timezone if org else "UTC"),
    )

    try:
        if appointment.google_calendar_event_id:
            _, new_etag = await _client.patch_event(
                session,
                org_id=appointment.org_id,
                user_id=user_id,
                calendar_id=calendar_id,
                event_id=appointment.google_calendar_event_id,
                event_body=event_body,
                etag=appointment.google_calendar_etag,
                http_client=http_client,
            )
            appointment.google_calendar_etag = new_etag
            await session.commit()
            await _da.touch_last_synced(
                session, token_id=token.id, when=datetime.now(UTC)
            )
            await session.commit()
            return "updated"

        event_id, etag = await _client.create_event(
            session,
            org_id=appointment.org_id,
            user_id=user_id,
            calendar_id=calendar_id,
            event_body=event_body,
            http_client=http_client,
        )
        appointment.google_calendar_event_id = event_id
        appointment.google_calendar_etag = etag
        await session.commit()
        await _da.touch_last_synced(
            session, token_id=token.id, when=datetime.now(UTC)
        )
        await session.commit()
        return "created"

    except GoogleCalendarEventGone:
        # Google side deleted it out from under us. Drop the local id +
        # recreate on the next reconciliation pass (task retries).
        appointment.google_calendar_event_id = None
        appointment.google_calendar_etag = None
        await session.commit()
        raise

    except GoogleCalendarConcurrencyConflict as exc:
        # v1: refuse to overwrite. Surface on the row's last_error so
        # the operator sees it. Don't null out anything.
        await _da.mark_status(
            session,
            token_id=token.id,
            status="error",
            error=f"concurrency_conflict: {exc}",
        )
        await session.commit()
        return "skipped"

    except GoogleCalendarTokenExpired as exc:
        # get_valid_access_token's refresh path already flipped the row
        # to 'revoked' when it caught invalid_grant. Nothing else to do
        # here beyond bubbling up so the task can back off.
        logger.warning(
            "google_calendar.sync_appointment token_expired appointment=%s "
            "user=%d err=%s",
            appointment_id,
            user_id,
            exc,
        )
        raise

    except GoogleCalendarError as exc:
        # Surface everything else on the token row's last_error so the
        # operator sees WHAT went wrong — the Celery task's retry loop
        # will re-attempt.
        await _da.mark_status(
            session,
            token_id=token.id,
            status="error",
            error=f"{type(exc).__name__}: {exc}",
        )
        await session.commit()
        raise


# --- Helpers -----------------------------------------------------------


async def _load_appointment(
    session: AsyncSession, appointment_id: uuid.UUID
) -> Appointment | None:
    from src.app.core.appointments import data_access as _appt_da

    return await _appt_da.get_appointment_by_id(session, appointment_id)


async def _load_contact(
    session: AsyncSession, contact_id: uuid.UUID | None
) -> Contact | None:
    if contact_id is None:
        return None
    return (
        await session.execute(select(Contact).where(Contact.id == contact_id))
    ).scalar_one_or_none()


async def _load_org(
    session: AsyncSession, org_id: uuid.UUID
) -> Organization | None:
    return (
        await session.execute(
            select(Organization).where(Organization.id == org_id)
        )
    ).scalar_one_or_none()


async def _ensure_primary_calendar_id(
    session: AsyncSession,
    *,
    token,
    http_client: httpx.AsyncClient | None,
) -> str:
    """Return the calendar id to write into. Google exposes the alias
    ``'primary'`` for every user's default calendar in every events
    endpoint, so we don't need to look up + cache the numeric id — that
    lookup requires the ``calendar.readonly`` scope which we don't
    request. Sticking with ``'primary'`` keeps the OAuth grant minimal
    (only ``calendar.events``)."""
    return "primary"


async def _delete_event_and_null_out(
    session: AsyncSession,
    *,
    appointment: Appointment,
    token,
    http_client: httpx.AsyncClient | None,
) -> None:
    """Idempotent delete + local cleanup. Even if Google returns a
    non-404 error we still null out the event_id locally so the CRM
    isn't left thinking the event exists when it doesn't."""
    calendar_id = await _ensure_primary_calendar_id(
        session, token=token, http_client=http_client
    )
    try:
        await _client.delete_event(
            session,
            org_id=appointment.org_id,
            user_id=token.user_id,
            calendar_id=calendar_id,
            event_id=appointment.google_calendar_event_id,
            http_client=http_client,
        )
    except GoogleCalendarEventGone:
        pass  # already gone, we're happy
    appointment.google_calendar_event_id = None
    appointment.google_calendar_etag = None
    await session.commit()
    await _da.touch_last_synced(
        session, token_id=token.id, when=datetime.now(UTC)
    )
    await session.commit()


def _build_event_body(
    *,
    appointment: Appointment,
    contact: Contact | None,
    org_timezone: str,
) -> dict[str, Any]:
    """Translate an Appointment ORM instance into the Google Calendar
    Event body shape.

    The event carries ``extendedProperties.private`` metadata so the
    Google-side event is traceable back to the CRM appointment id —
    useful if we later ship the v2 two-way sync (Google → CRM via
    push notifications), or for manual debugging.
    """
    start_at = appointment.scheduled_at
    end_at = start_at + timedelta(minutes=int(appointment.duration_min or 30))

    description_parts: list[str] = []
    if appointment.purpose:
        description_parts.append(f"Purpose: {appointment.purpose}")
    description_parts.append(f"CRM appointment id: {appointment.id}")

    body: dict[str, Any] = {
        "summary": appointment.title,
        "description": "\n".join(description_parts),
        "start": {
            "dateTime": start_at.isoformat(),
            "timeZone": org_timezone,
        },
        "end": {
            "dateTime": end_at.isoformat(),
            "timeZone": org_timezone,
        },
        "reminders": {"useDefault": True},
        "extendedProperties": {
            "private": {
                "crm_appointment_id": str(appointment.id),
                "crm_org_id": str(appointment.org_id),
            },
        },
    }
    if appointment.location:
        body["location"] = appointment.location

    # Contact-as-attendee. Skipped when the contact has no email
    # (Google requires ``email`` on every attendee entry) — the event
    # still lands in the assignee's calendar, just without a formal
    # attendee record.
    if contact is not None and contact.email:
        body["attendees"] = [
            {
                "email": contact.email,
                "displayName": contact.full_name,
            }
        ]
    return body


async def _resolve_login_id(
    session: AsyncSession, user_uuid: Any
) -> int | None:
    """Translate the app-wide UUID identifier (as stored on
    ``tbl_appointments.assigned_to_id``) into the BIGINT
    ``tbl_user_login.id`` used by the token row so we can compare
    "does this appointment's assignee match the token's user?".

    Match paths (either wins):

    * ``tbl_user_login.legacy_uuid`` = UUID directly
    * ``tbl_user_login.user_id`` = ``'usr_' || hex-no-hyphens``

    Returns ``None`` when the UUID doesn't map to any login row.
    """
    from sqlalchemy import text

    if user_uuid is None:
        return None
    uuid_str = str(user_uuid)
    ext = "usr_" + uuid_str.replace("-", "")
    row = await session.execute(
        text(
            "SELECT id FROM tbl_user_login "
            "WHERE legacy_uuid::text = :uuid OR user_id = :ext "
            "LIMIT 1"
        ),
        {"uuid": uuid_str, "ext": ext},
    )
    r = row.first()
    return int(r[0]) if r else None


def _org_id_of(
    appointment: Appointment | None, _user_id: int
) -> uuid.UUID:
    """Extract ``org_id`` for the token lookup. When the appointment
    exists we use its org; on the delete-because-appointment-gone
    path we synthesise a zero UUID which the caller's ``get_active_
    token_for_user`` will simply miss — safe."""
    if appointment is not None:
        return appointment.org_id
    return uuid.UUID(int=0)


__all__ = ["sync_appointment"]
