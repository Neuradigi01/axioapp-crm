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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.custom_events import data_access as _da
from src.app.core.custom_events.entity_registry import (
    ENTITY_REGISTRY,
    SUPPORTED_ENTITY_TYPES,
)
from src.app.core.custom_events.models import CustomEvent, CustomEventOccurrence
from src.app.core.custom_events.schemas import (
    CustomEventCreate,
    CustomEventFireResponse,
    CustomEventListItem,
    CustomEventRead,
    CustomEventUpdate,
    ScheduleConfig,
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
    schedule: ScheduleConfig | None = None
    if row.schedule_type == "date_field":
        schedule = ScheduleConfig(
            source=row.schedule_source,  # type: ignore[arg-type]
            field_ref=row.schedule_field_ref or "",
            offset_days=row.schedule_offset_days or 0,
            recurring=row.schedule_recurring or "none",  # type: ignore[arg-type]
            # ``is not None`` rather than ``or``: hour 0 (midnight) is a
            # valid pick and must not read back as the 09:00 default.
            hour_local=row.schedule_hour_local if row.schedule_hour_local is not None else 9,
            minute_local=row.schedule_minute_local or 0,
        )
    return CustomEventRead(
        id=row.id,
        event_key=row.event_key,
        name=row.name,
        description=row.description,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        entity_type=row.entity_type,  # type: ignore[arg-type]
        schedule_type=row.schedule_type,  # type: ignore[arg-type]
        schedule=schedule,
    )


async def list_date_field_catalog(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    entity_type: str = "contact",
) -> list[dict[str, Any]]:
    """Return every date/datetime-typed field an event can subscribe
    to on the requested entity. Backs the create-event modal's
    field picker.

    * ``group=f"{Entity} · System fields"`` — physical columns
      declared in :data:`ENTITY_REGISTRY[entity_type].system_date_fields`.
    * ``group=f"{Entity} · Custom fields"`` — the org's
      ``custom_field_definitions`` of type ``date``/``datetime`` for
      the entity's ``custom_fields_entity_key``.

    Raises ``HTTPException(422)`` if ``entity_type`` isn't in the
    supported set — routes catch this via FastAPI's default handler.
    """
    from src.app.core.custom_fields import data_access as cf_da
    from src.app.core.custom_fields.models import FieldType

    if entity_type not in SUPPORTED_ENTITY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unsupported entity_type {entity_type!r}. Supported: "
                f"{sorted(SUPPORTED_ENTITY_TYPES)}."
            ),
        )
    spec = ENTITY_REGISTRY[entity_type]

    entries: list[dict[str, Any]] = []
    system_group = f"{spec.label} · System fields"
    custom_group = f"{spec.label} · Custom fields"
    for sys_field in spec.system_date_fields:
        entries.append(
            {
                "source": "system",
                "field_ref": sys_field.column,
                "label": sys_field.label,
                "group": system_group,
                "recurring_hint": sys_field.recurring_hint,
            }
        )

    definitions = await cf_da.list_fields_query(
        session,
        entity_type=spec.custom_fields_entity_key,
        include_hidden=False,
    )
    for definition in definitions:
        if definition.field_type not in (FieldType.date, FieldType.datetime):
            continue
        entries.append(
            {
                "source": "custom",
                "field_ref": definition.field_key,
                "label": definition.field_label or definition.field_key,
                "group": custom_group,
                "recurring_hint": "none",
            }
        )
    # System group first, then custom, then alphabetical by label.
    entries.sort(key=lambda e: (e["group"] != system_group, e["label"].lower()))
    return entries


def _validate_field_ref(
    source: str,
    field_ref: str,
    catalog: list[dict[str, Any]],
) -> None:
    """Ensure the caller's (source, field_ref) pair is a real entry in
    the catalog. Guards against a client sending a stale or fabricated
    field key that would either 500 the sweeper or (worse) inject SQL
    when the sweeper substitutes ``schedule_field_ref`` into its WHERE
    clause on the system branch."""
    match = next(
        (e for e in catalog if e["source"] == source and e["field_ref"] == field_ref),
        None,
    )
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Date field {field_ref!r} (source={source!r}) is not available "
                f"on contacts. Refresh the field picker and pick again."
            ),
        )


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
    entity_type: str | None = None,
) -> list[CustomEventListItem]:
    """Return every live event definition for the org, enriched with
    per-event fire counts for the last 30 days.

    ``entity_type`` — when set, only events whose ``entity_type``
    matches are returned. The contact-detail Log Event dropdown
    passes ``'contact'`` here to hide lead/appointment-scoped events
    that wouldn't fit that surface's context.

    Workflow-usage counts are stubbed at 0 for v1 — a follow-up wires
    the workflows-service lookup (small round-trip, keeps this method
    signature stable)."""
    rows = await _da.list_events(session, org_id=org_id)
    if entity_type is not None:
        rows = [r for r in rows if r.entity_type == entity_type]
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom event not found.")
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

    existing = await _da.get_event_by_key(session, org_id=org_id, event_key=payload.event_key)
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
        entity_type=payload.entity_type,
    )
    if payload.schedule_type == "date_field":
        assert payload.schedule is not None  # validator guarantees this
        catalog = await list_date_field_catalog(
            session, org_id=org_id, entity_type=payload.entity_type
        )
        _validate_field_ref(payload.schedule.source, payload.schedule.field_ref, catalog)
        row.schedule_type = "date_field"
        row.schedule_source = payload.schedule.source
        row.schedule_field_ref = payload.schedule.field_ref
        row.schedule_offset_days = payload.schedule.offset_days
        row.schedule_recurring = payload.schedule.recurring
        row.schedule_hour_local = payload.schedule.hour_local
        row.schedule_minute_local = payload.schedule.minute_local
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom event not found.")
    before = _snapshot(row)
    changes = payload.model_dump(exclude_unset=True)
    # Apply plain-scalar edits first (name, description).
    for key in ("name", "description"):
        if key in changes:
            setattr(row, key, changes[key])
    # Schedule mutation: only when the caller supplied schedule_type
    # (Pydantic's coupling validator has already enforced schedule
    # presence/absence matches the type).
    if payload.schedule_type is not None:
        if payload.schedule_type == "manual":
            row.schedule_type = "manual"
            row.schedule_source = None
            row.schedule_field_ref = None
            row.schedule_offset_days = None
            row.schedule_recurring = None
            row.schedule_hour_local = None
            row.schedule_minute_local = None
        else:
            assert payload.schedule is not None
            catalog = await list_date_field_catalog(
                session, org_id=org_id, entity_type=row.entity_type
            )
            _validate_field_ref(payload.schedule.source, payload.schedule.field_ref, catalog)
            row.schedule_type = "date_field"
            row.schedule_source = payload.schedule.source
            row.schedule_field_ref = payload.schedule.field_ref
            row.schedule_offset_days = payload.schedule.offset_days
            row.schedule_recurring = payload.schedule.recurring
            row.schedule_hour_local = payload.schedule.hour_local
            row.schedule_minute_local = payload.schedule.minute_local
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom event not found.")

    # Manual fire is allowed for events of any entity_type — staff on
    # a Contact page can force-fire a lead/appointment event without
    # waiting for the scheduled sweep. The occurrence is recorded
    # against the contact (that's the surface the fire happened on);
    # subscribed workflows still receive the bus publish and run.
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

    recurring = event.schedule_recurring or "none"
    period_key = _period_key_for(recurring, datetime.now(UTC))
    occurrence = CustomEventOccurrence(
        org_id=org_id,
        event_id=event.id,
        contact_id=contact_id,
        entity_type="contact",  # manual fires are contact-scoped
        entity_id=contact_id,
        fired_by_user_id=actor_id,
        payload=payload or {},
        recurring_mode=recurring,
        period_key=period_key,
    )
    _da.insert_occurrence(session, occurrence)
    try:
        await session.commit()
    except IntegrityError as exc:
        # Dedup index tripped — this (event, contact, period) already
        # fired. For MANUAL fires that's a race between two staffers
        # clicking the button simultaneously, which is rare enough to
        # surface as 409 rather than silently swallow. For the sweeper's
        # `_fire_scheduled_for_contact` helper we short-circuit before
        # this path.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This event has already fired for this contact in the current "
                f"period ({period_key!r})."
            ),
        ) from exc
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


def _period_key_for(recurring: str, when: datetime) -> str:
    """Compute the dedup grain key that lands in
    ``tbl_custom_event_occurrences.period_key`` — matches the
    ``ux_custom_event_occ_dedup`` partial unique index (migration 0227).

    * ``'none'``    → empty string (single fire per contact per event ever)
    * ``'yearly'``  → ``'YYYY'`` (birthdays, anniversaries)
    * ``'monthly'`` → ``'YYYY-MM'`` (rent reminders, subscription refreshes)
    """
    if recurring == "yearly":
        return f"{when.year:04d}"
    if recurring == "monthly":
        return f"{when.year:04d}-{when.month:02d}"
    return ""


async def sweep_and_fire_for_org(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    org_hour_local: int,
    org_minute_local: int,
    today_local: date_type,
) -> dict[str, int]:
    """Run the date-triggered sweep for a single org.

    For every ``date_field`` event on this org scheduled for the org's
    current local 5-minute slot (``schedule_hour_local`` ==
    ``org_hour_local`` and ``schedule_minute_local`` ==
    ``org_minute_local``, already floored to a multiple of 5):

      1. Compute the target date = ``today_local - offset_days``.
      2. Find every contact in this org whose watched date field
         matches the target (system column OR JSONB custom-field
         value). For yearly recurring events we match on
         ``(month, day)`` only; monthly on ``(day)``; none on the
         full date.
      3. Fire the event for each match. The occurrence table's
         partial unique index absorbs re-runs (double-tick, worker
         restart, retry) so at most one row per contact per period.

    Returns per-event fire counts for logging / metrics.
    """
    from datetime import timedelta

    from sqlalchemy import Date, cast, extract, select

    events = await _da.list_scheduled_events_for_slot(
        session, org_id=org_id, hour_local=org_hour_local, minute_local=org_minute_local
    )
    fire_counts: dict[str, int] = {}
    for event in events:
        # Cache scalar attributes off the ORM row up-front — the
        # ``_fire_scheduled_occurrence`` helper does its own
        # ``session.commit()`` which expires every attached instance's
        # attributes. Subsequent per-loop access would trigger a lazy
        # reload outside the greenlet context. Caching sidesteps it.
        event_key = event.event_key
        entity_type = event.entity_type
        offset = event.schedule_offset_days or 0
        target = today_local - timedelta(days=offset)
        recurring = event.schedule_recurring or "none"

        spec = ENTITY_REGISTRY.get(entity_type)
        if spec is None:
            logger.warning(
                "custom_events.sweep: skipping event %s — unknown entity_type %r",
                event.id,
                entity_type,
            )
            continue
        Model = spec.model_getter()

        stmt = select(Model).where(Model.org_id == org_id)
        if event.schedule_source == "system":
            column_name = event.schedule_field_ref or ""
            # Allowlist check — only known system columns are allowed
            # (defence in depth; the validator at create/update already
            # gated the input).
            known_columns = {sd.column for sd in spec.system_date_fields}
            if column_name not in known_columns:
                logger.warning(
                    "custom_events.sweep: skipping event %s — unknown %s system column %r",
                    event.id,
                    entity_type,
                    column_name,
                )
                continue
            column = getattr(Model, column_name)
            if recurring == "yearly":
                stmt = stmt.where(
                    extract("month", column) == target.month,
                    extract("day", column) == target.day,
                )
            elif recurring == "monthly":
                stmt = stmt.where(extract("day", column) == target.day)
            else:
                stmt = stmt.where(cast(column, Date) == target)
        else:
            # Custom field lives at <entity>.custom_data->>'<field_ref>'.
            field_ref = event.schedule_field_ref or ""
            date_expr = cast(
                Model.custom_data.op("->>")(field_ref),
                Date,
            )
            if recurring == "yearly":
                stmt = stmt.where(
                    extract("month", date_expr) == target.month,
                    extract("day", date_expr) == target.day,
                )
            elif recurring == "monthly":
                stmt = stmt.where(extract("day", date_expr) == target.day)
            else:
                stmt = stmt.where(date_expr == target)

        result = await session.execute(stmt)
        matches = list(result.scalars().all())
        # Snapshot everything the fire helper needs; the commits inside
        # the loop expire the ORM row otherwise.
        event_snapshot = _EventSnapshot(
            id=event.id,
            org_id=event.org_id,
            event_key=event_key,
            name=event.name,
            description=event.description,
            entity_type=entity_type,
            contact_id_ref=spec.contact_id_ref,
            schedule_source=event.schedule_source,
            schedule_field_ref=event.schedule_field_ref,
            schedule_offset_days=event.schedule_offset_days,
            schedule_recurring=recurring,
        )
        fired = 0
        for row in matches:
            try:
                await _fire_scheduled_occurrence(
                    session,
                    event=event_snapshot,
                    entity_row=row,
                    fired_at=datetime.now(UTC),
                )
                fired += 1
            except IntegrityError:
                # Already fired this contact for this period — that's
                # the whole point of the dedup index. Silent skip.
                await session.rollback()
        fire_counts[event_key] = fired
    return fire_counts


@dataclass(frozen=True, slots=True)
class _EventSnapshot:
    """Detached snapshot of an event definition — sidesteps
    session-expiration on the ORM row after per-iteration commits."""

    id: uuid.UUID
    org_id: uuid.UUID
    event_key: str
    name: str
    description: str | None
    entity_type: str
    # Attribute name to reach the related contact from the entity row.
    # 'id' for contact (the row IS the contact), 'contact_id' for
    # lead / appointment.
    contact_id_ref: str
    schedule_source: str | None
    schedule_field_ref: str | None
    schedule_offset_days: int | None
    schedule_recurring: str


async def _fire_scheduled_occurrence(
    session: AsyncSession,
    *,
    event: _EventSnapshot,
    entity_row: Any,
    fired_at: datetime,
) -> None:
    """Persist an occurrence + publish on the bus for a sweeper-driven
    fire. Isolated from :func:`fire_event` so the sweeper doesn't have
    to fake an ``actor_id`` or re-run the manual-fire's cross-org
    contact validation (the sweeper already has both loaded).

    ``entity_row`` is whatever the sweeper's SELECT returned — a
    Contact for entity_type='contact', a Lead for 'lead', an
    Appointment for 'appointment'. We use ``event.contact_id_ref`` to
    reach the related contact so the workflow envelope always carries
    contact-shaped variables (``{{ contact.email }}`` etc.).
    """
    recurring = event.schedule_recurring
    period_key = _period_key_for(recurring, fired_at)
    payload = {
        "scheduled": True,
        "entity_type": event.entity_type,
        "field_source": event.schedule_source,
        "field_ref": event.schedule_field_ref,
        "offset_days": event.schedule_offset_days,
        "recurring": recurring,
    }
    # Cache entity + contact fields BEFORE commit — same expiration
    # risk as events. Read whatever the envelope needs into locals.
    entity_id = entity_row.id
    entity_custom_data = getattr(entity_row, "custom_data", None) or {}
    contact_id = getattr(entity_row, event.contact_id_ref, None)
    if event.entity_type == "contact":
        contact = entity_row
    else:
        # Fetch the related contact so the envelope's ``contact`` block
        # is populated for lead/appointment fires.
        from src.app.core.contacts.data_access import get_contact

        contact = await get_contact(session, contact_id) if contact_id else None

    contact_full_name = getattr(contact, "full_name", None)
    contact_email = getattr(contact, "email", None)
    contact_phone = getattr(contact, "phone", None)
    contact_custom_data = getattr(contact, "custom_data", None) or {}

    occurrence = CustomEventOccurrence(
        org_id=event.org_id,
        event_id=event.id,
        contact_id=contact_id,
        entity_type=event.entity_type,
        entity_id=entity_id,
        fired_by_user_id=None,  # system-fire — not a human actor
        payload=payload,
        recurring_mode=recurring,
        period_key=period_key,
    )
    _da.insert_occurrence(session, occurrence)
    await session.commit()  # raises IntegrityError → dedup skip in caller
    occurrence_id = occurrence.id
    occurrence_fired_at = occurrence.fired_at

    envelope: dict[str, Any] = {
        "event_key": event.event_key,
        "event_definition": {
            "id": str(event.id),
            "key": event.event_key,
            "name": event.name,
            "description": event.description,
            "entity_type": event.entity_type,
        },
        "occurrence_id": str(occurrence_id),
        "entity_type": event.entity_type,
        "entity_id": str(entity_id),
        "contact_id": str(contact_id) if contact_id else None,
        "fired_by_user_id": None,
        "fired_at": occurrence_fired_at.isoformat(),
        "payload": payload,
        # ``contact`` is always populated when we could resolve one (the
        # sweeper only fires on rows with a contact_id-ref present) so
        # workflow templates can read ``{{ contact.email }}`` regardless
        # of whether the event was contact/lead/appointment scoped.
        "contact": {
            "id": str(contact_id) if contact_id else None,
            "full_name": contact_full_name,
            "email": contact_email,
            "phone": contact_phone,
            "custom_data": contact_custom_data,
        },
        # Also expose the source entity block (contact / lead /
        # appointment) so templates that want entity-specific fields
        # (like a Lead's expected_close_date) can reach them.
        event.entity_type: {
            "id": str(entity_id),
            "custom_data": entity_custom_data,
        },
    }
    event_type = f"custom.{event.event_key}"
    try:
        await bus.publish(
            event_type,
            envelope,
            org_id=event.org_id,
            event_id=str(occurrence_id),
        )
    except Exception:
        logger.exception(
            "custom_events.scheduled_fire: bus.publish failed event_type=%s occurrence_id=%s",
            event_type,
            occurrence_id,
        )


# --- Types (imported here to keep the sweeper signature readable) --------

from datetime import date as date_type  # noqa: E402

__all__ = [
    "create_event",
    "delete_event",
    "fire_event",
    "get_event",
    "list_date_field_catalog",
    "list_events",
    "list_for_workflow_picker",
    "sweep_and_fire_for_org",
    "update_event",
]
