"""HTTP routes for custom events.

Admin surface (JWT-gated by permission):

  GET    /api/v1/custom-events                 list — anyone with read
  POST   /api/v1/custom-events                 create — manage
  GET    /api/v1/custom-events/{id}            single — read
  PUT    /api/v1/custom-events/{id}            edit — manage
  DELETE /api/v1/custom-events/{id}            soft-delete — manage
  POST   /api/v1/custom-events/{id}/fire       fire — fire permission
  GET    /api/v1/custom-events/{id}/occurrences  history — read

  GET    /api/v1/contacts/{contact_id}/custom-events
                                              contact timeline — read

Permission split:

  * ``custom_events.read``  — everyone who logs in should be able to
    see WHICH events exist so the "Log event" dropdown on the contact
    page shows something.
  * ``custom_events.manage`` — Owner/Admin: create / edit / delete
    event definitions (rare operation, high blast radius — renaming a
    reserved event breaks every workflow that subscribed).
  * ``custom_events.fire``  — any role that touches contacts: the
    salesperson clicking "Log event" needs this. Default-granted to
    every seeded role except read-only viewers.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.custom_events import data_access as _da
from src.app.core.custom_events import service
from src.app.core.custom_events.schemas import (
    CustomEventCreate,
    CustomEventFireRequest,
    CustomEventFireResponse,
    CustomEventListItem,
    CustomEventOccurrenceRead,
    CustomEventRead,
    CustomEventUpdate,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/custom-events", tags=["Custom Events"])


@router.get("", response_model=list[CustomEventListItem])
async def list_custom_events_endpoint(
    entity: str | None = Query(
        default=None,
        description=(
            "Optional entity filter — 'contact' | 'lead' | 'appointment'. "
            "When set, only events whose entity_type matches are returned. "
            "Used by the contact-detail 'Log event' dropdown to hide "
            "events tied to other entities."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("custom_events.read")),
) -> list[CustomEventListItem]:
    return await service.list_events(db, org_id=user.org_id, entity_type=entity)


@router.get("/date-field-catalog")
async def list_date_field_catalog_endpoint(
    entity: str = Query(default="contact"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("custom_events.manage")),
) -> list[dict]:
    """Return every date/datetime field an event can subscribe to on
    ``entity``, grouped by source (System / Custom). Feeds the
    create-event modal's date-field picker.

    ``entity`` is one of ``contact`` (default), ``lead``,
    ``appointment``. Unsupported values 422.

    Gated on ``custom_events.manage`` — only Owner/Admin ever needs
    this endpoint (staff-visible pickers don't need it)."""
    return await service.list_date_field_catalog(
        db, org_id=user.org_id, entity_type=entity
    )


@router.get("/entities")
async def list_supported_entities_endpoint(
    _user: User = Depends(require_permissions("custom_events.manage")),
) -> list[dict]:
    """Return the entity types a custom event can bind to
    (``contact`` / ``lead`` / ``appointment``) with their human labels.
    Feeds the create-event modal's entity picker."""
    from src.app.core.custom_events.entity_registry import ENTITY_REGISTRY

    return [
        {"key": key, "label": spec.label}
        for key, spec in ENTITY_REGISTRY.items()
    ]


@router.post(
    "",
    response_model=CustomEventRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_custom_event_endpoint(
    payload: CustomEventCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("custom_events.manage")),
) -> CustomEventRead:
    return await service.create_event(
        db,
        org_id=user.org_id,
        actor_id=user.legacy_uuid,
        payload=payload,
    )


@router.get("/{event_id}", response_model=CustomEventRead)
async def get_custom_event_endpoint(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("custom_events.read")),
) -> CustomEventRead:
    return await service.get_event(db, org_id=user.org_id, event_id=event_id)


@router.put("/{event_id}", response_model=CustomEventRead)
async def update_custom_event_endpoint(
    event_id: uuid.UUID,
    payload: CustomEventUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("custom_events.manage")),
) -> CustomEventRead:
    return await service.update_event(
        db,
        org_id=user.org_id,
        actor_id=user.legacy_uuid,
        event_id=event_id,
        payload=payload,
    )


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_event_endpoint(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("custom_events.manage")),
) -> Response:
    await service.delete_event(
        db,
        org_id=user.org_id,
        actor_id=user.legacy_uuid,
        event_id=event_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{event_id}/fire",
    response_model=CustomEventFireResponse,
    status_code=status.HTTP_201_CREATED,
)
async def fire_custom_event_endpoint(
    event_id: uuid.UUID,
    payload: CustomEventFireRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("custom_events.fire")),
) -> CustomEventFireResponse:
    """Fire this event — persists an occurrence row and publishes on
    the bus so subscribed workflows run.
    """
    return await service.fire_event(
        db,
        org_id=user.org_id,
        actor_id=user.legacy_uuid,
        event_id=event_id,
        contact_id=payload.contact_id,
        payload=payload.payload,
    )


@router.get(
    "/{event_id}/occurrences",
    response_model=list[CustomEventOccurrenceRead],
)
async def list_occurrences_endpoint(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("custom_events.read")),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[CustomEventOccurrenceRead]:
    rows, _total = await _da.list_occurrences(
        db,
        org_id=user.org_id,
        event_id=event_id,
        limit=limit,
        offset=offset,
    )
    return [CustomEventOccurrenceRead.model_validate(r) for r in rows]


# --- Contact timeline read (mounted on the contact router surface) ------

# Kept in this module (not contacts) so the timeline query stays
# collocated with the write path. Router registered under the same
# `/custom-events` prefix so main.py has ONE include_router call.


@router.get("/by-contact/{contact_id}")
async def list_custom_events_for_contact_endpoint(
    contact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("custom_events.read")),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    """Return every custom event ever fired against this contact,
    newest first, joined with the event definition so the caller
    renders the row without a second round-trip."""
    return await _da.list_occurrences_for_contact(
        db,
        org_id=user.org_id,
        contact_id=contact_id,
        limit=limit,
    )


__all__ = ["router"]
