"""Service layer for custom events — the only layer that touches
transactions.

Five public entry points:

  * ``list_events`` / ``get_event`` — list + one-row reads. The list
    endpoint enriches with ``fires_last_30d`` in one batched query
    (no N+1).
  * ``create_event`` — Owner/Admin only. Validates unique key per org.
  * ``update_event`` — patch-style. ``event_key`` is intentionally
    immutable (renames would silently break subscribed workflows).
  * ``delete_event`` — soft-delete (``deleted_at``). A future re-create
    with the same key is allowed because the unique index is partial
    (``WHERE deleted_at IS NULL``).
  * ``fire_event`` — the "log this event on a contact" call. Validates
    the contact belongs to the same org, persists an occurrence row,
    then publishes ``custom.<event_key>`` on the bus so subscribed
    workflows run.

The bus publish happens AFTER the DB commit so a workflow never
receives an event whose occurrence row failed to persist. This
mirrors the pattern in ``core.leads.service.create_lead`` — the
canonical example.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.custom_events import data_access as _da
from src.app.core.custom_events.models import CustomEvent, CustomEventOccurrence
from src.app.core.custom_events.schemas import (
    CustomEventCreate,
    CustomEventFireResponse,
    CustomEventListItem,
    CustomEventRead,
    CustomEventUpdate,
)
from src.app.core.events import bus

logger = logging.getLogger(__name__)


# Reserved keys that would collide with core event namespaces
# (`user.*`, `lead.*`, `contact.*`, `appointment.*`, etc.). Custom
# events always publish under the `custom.<key>` prefix, so a raw
# collision is technically impossible — but reserving these guards
# against operator confusion (e.g. someone names their event
# "lead_created" expecting it to fire on real lead creation).
_RESERVED_KEY_PREFIXES: tuple[str, ...] = (
    "user_",
    "lead_",
    "contact_",
    "appointment_",
    "walk_in_",
    "quote_",
    "invoice_",
    "email_",
    "whatsapp_",
    "review_",
    "time_",
    "sms_",
)


def _to_read(row: CustomEvent) -> CustomEventRead:
    return CustomEventRead.model_validate(row)


def _snapshot(row: CustomEvent) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "event_key": row.event_key,
        "name": row.name,
        "description": row.description,
    }


async def list_events(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> list[CustomEventListItem]:
    """Return every live event definition for the org, enriched with
    per-event fire counts for the last 30 days.

    Workflow-usage counts are stubbed at 0 for v1 — a follow-up wires
    the workflows-service lookup (small round-trip, keeps this method
    signature stable)."""
    rows = await _da.list_events(session, org_id=org_id)
    ids = [r.id for r in rows]
    fires = await _da.count_fires_last_30d(session, org_id=org_id, event_ids=ids)
    return [
        CustomEventListItem(
            **_to_read(r).model_dump(),
            fires_last_30d=fires.get(r.id, 0),
            workflows_using_count=0,
        )
        for r in rows
    ]


async def get_event(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    event_id: uuid.UUID,
) -> CustomEventRead:
    row = await _da.get_event(session, org_id=org_id, event_id=event_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Custom event not found."
        )
    return _to_read(row)


async def create_event(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    payload: CustomEventCreate,
) -> CustomEventRead:
    """Insert a new event definition. 409 on duplicate key."""
    for reserved in _RESERVED_KEY_PREFIXES:
        if payload.event_key.startswith(reserved):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"event_key {payload.event_key!r} starts with a reserved "
                    f"prefix. Pick a name that doesn't shadow the built-in "
                    f"event namespaces (lead.*, contact.*, appointment.*, ...)."
                ),
            )

    existing = await _da.get_event_by_key(
        session, org_id=org_id, event_key=payload.event_key
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An event with key {payload.event_key!r} already exists.",
        )

    row = CustomEvent(
        org_id=org_id,
        event_key=payload.event_key,
        name=payload.name,
        description=payload.description,
        created_by_user_id=actor_id,
    )
    _da.insert_event(session, row)
    await session.commit()
    await session.refresh(row)

    await audit.log(
        "custom_events.created",
        entity_type="custom_event",
        entity_id=row.id,
        after=_snapshot(row),
    )
    return _to_read(row)


async def update_event(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    event_id: uuid.UUID,
    payload: CustomEventUpdate,
) -> CustomEventRead:
    row = await _da.get_event(session, org_id=org_id, event_id=event_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Custom event not found."
        )
    before = _snapshot(row)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(row, key, value)
    row.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)

    await audit.log(
        "custom_events.updated",
        entity_type="custom_event",
        entity_id=row.id,
        before=before,
        after=_snapshot(row),
        user_id=actor_id,
    )
    return _to_read(row)


async def delete_event(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    event_id: uuid.UUID,
) -> None:
    """Soft-delete. Occurrences stay for reporting; the partial unique
    index allows a future recreate of the same event_key."""
    row = await _da.get_event(session, org_id=org_id, event_id=event_id)
    if row is None:
        # Idempotent — already gone.
        return
    before = _snapshot(row)
    row.deleted_at = datetime.now(UTC)
    row.updated_at = row.deleted_at
    await session.commit()

    await audit.log(
        "custom_events.deleted",
        entity_type="custom_event",
        entity_id=event_id,
        before=before,
        user_id=actor_id,
    )


async def fire_event(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    event_id: uuid.UUID,
    contact_id: uuid.UUID | None,
    payload: dict[str, Any] | None,
) -> CustomEventFireResponse:
    """Log an occurrence + publish on the bus so workflows react.

    ``actor_id=None`` is legitimate when a workflow (not a human) fires
    the event — bus subscribers see ``fired_by_user_id`` NULL in the
    envelope.

    If ``contact_id`` is supplied, we validate the contact exists in
    this org (cross-org write attempt → 404). If omitted, the event
    fires as a system-scope event (no contact context).
    """
    event = await _da.get_event(session, org_id=org_id, event_id=event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Custom event not found."
        )

    resolved_contact = None
    if contact_id is not None:
        # Lazy import — avoids a hard dependency cycle at module load.
        from src.app.core.contacts.data_access import get_contact

        resolved_contact = await get_contact(session, contact_id)
        if resolved_contact is None or resolved_contact.org_id != org_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contact not found in this workspace.",
            )

    occurrence = CustomEventOccurrence(
        org_id=org_id,
        event_id=event.id,
        contact_id=contact_id,
        fired_by_user_id=actor_id,
        payload=payload or {},
    )
    _da.insert_occurrence(session, occurrence)
    await session.commit()
    await session.refresh(occurrence)

    # Publish AFTER commit so a workflow never sees an event whose
    # occurrence row failed to persist.
    envelope: dict[str, Any] = {
        "event_key": event.event_key,
        "event_definition": {
            "id": str(event.id),
            "key": event.event_key,
            "name": event.name,
            "description": event.description,
        },
        "occurrence_id": str(occurrence.id),
        "contact_id": str(contact_id) if contact_id else None,
        "fired_by_user_id": str(actor_id) if actor_id else None,
        "fired_at": occurrence.fired_at.isoformat(),
        "payload": payload or {},
    }
    if resolved_contact is not None:
        envelope["contact"] = {
            "id": str(resolved_contact.id),
            "full_name": getattr(resolved_contact, "full_name", None),
            "email": getattr(resolved_contact, "email", None),
            "phone": getattr(resolved_contact, "phone", None),
            "custom_data": getattr(resolved_contact, "custom_data", None) or {},
        }

    event_type = f"custom.{event.event_key}"
    try:
        await bus.publish(
            event_type,
            envelope,
            org_id=org_id,
            event_id=str(occurrence.id),
        )
    except Exception:
        # Bus publish failures are logged but do NOT roll back the
        # occurrence row — a workflow that missed one fire is
        # recoverable via manual re-fire, whereas a lost audit trail
        # is not. Matches the pattern from bus.publish's own handler
        # (failures swallowed there too).
        logger.exception(
            "custom_events.fire: bus.publish failed event_type=%s occurrence_id=%s",
            event_type,
            occurrence.id,
        )

    await audit.log(
        "custom_events.fired",
        entity_type="custom_event",
        entity_id=event.id,
        after={
            "event_key": event.event_key,
            "occurrence_id": str(occurrence.id),
            "contact_id": str(contact_id) if contact_id else None,
        },
        user_id=actor_id,
    )

    return CustomEventFireResponse(
        occurrence_id=occurrence.id,
        event_type=event_type,
        fired_at=occurrence.fired_at,
    )


async def list_for_workflow_picker(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Return the org's live custom events shaped like a workflow
    trigger-picker catalog entry (``event_type``, ``label``,
    ``description``, ``sample_payload``). The workflows router calls
    this and merges the result with the core catalog.
    """
    rows = await _da.list_events(session, org_id=org_id)
    entries: list[dict[str, Any]] = []
    for row in rows:
        event_type = f"custom.{row.event_key}"
        entries.append(
            {
                "event_type": event_type,
                "label": row.name,
                "description": row.description
                or f"Fires when staff logs {row.event_key!r} on a contact.",
                "sample_payload": {
                    "event_key": row.event_key,
                    "event_definition": {
                        "id": str(row.id),
                        "key": row.event_key,
                        "name": row.name,
                    },
                    "occurrence_id": "00000000-0000-0000-0000-000000000000",
                    "contact_id": "00000000-0000-0000-0000-000000000000",
                    "fired_at": "2026-09-11T12:00:00+00:00",
                    "payload": {},
                    "contact": {
                        "id": "00000000-0000-0000-0000-000000000000",
                        "full_name": "Asha Mehta",
                        "email": "asha@example.com",
                        "phone": "+919876543210",
                        "custom_data": {},
                    },
                },
                "condition_fields": [],
                "is_custom": True,
            }
        )
    return entries


__all__ = [
    "create_event",
    "delete_event",
    "fire_event",
    "get_event",
    "list_events",
    "list_for_workflow_picker",
    "update_event",
]
