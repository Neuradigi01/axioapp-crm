"""HTTP routes for `contacts`.

Routes mounted under ``/api/v1/contacts``. Reads require
``contacts.read``; mutations require ``contacts.write``. Tenant scoping
is automatic via the ORM filter on `TenantScoped`.

  GET    /contacts              → paginated list, q/source/tag/custom.* filters
  POST   /contacts              → create
  GET    /contacts/{id}         → get one
  PATCH  /contacts/{id}         → partial update
  DELETE /contacts/{id}         → delete

The dynamic ``custom.<key>=<value>`` filter is parsed off
``Request.query_params`` because FastAPI's typed Query params don't
support arbitrary prefixed names.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.contacts.schemas import (
    ContactBulkAddTag,
    ContactBulkAddTagResult,
    ContactBulkDelete,
    ContactBulkDeleteResult,
    ContactBulkReassign,
    ContactBulkReassignResult,
    ContactCreate,
    ContactListItem,
    ContactListResponse,
    ContactOut,
    ContactReassign,
    ContactUpdate,
)
from src.app.core.contacts.service import (
    bulk_add_tag_contacts,
    bulk_delete_contacts,
    bulk_reassign_contacts,
    create_contact,
    delete_contact,
    get_contact,
    list_contacts,
    reassign_contact,
    update_contact,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/contacts", tags=["Contacts"])

_CUSTOM_PREFIX = "custom."


def _extract_custom_filters(request: Request) -> list[tuple[str, str]]:
    """Pull every `custom.<key>=<value>` pair out of the query string."""
    out: list[tuple[str, str]] = []
    for raw_key, value in request.query_params.multi_items():
        if raw_key.startswith(_CUSTOM_PREFIX) and len(raw_key) > len(_CUSTOM_PREFIX):
            out.append((raw_key[len(_CUSTOM_PREFIX) :], value))
    return out


@router.get("", response_model=ContactListResponse)
async def list_contacts_endpoint(
    request: Request,
    q: str | None = Query(default=None, max_length=255),
    source: str | None = Query(default=None, max_length=64),
    tag: str | None = Query(default=None, max_length=64),
    assigned_to_id: uuid.UUID | None = Query(default=None),
    sort: Literal["full_name", "created_at", "last_activity_at"] = Query(
        default="created_at"
    ),
    order: Literal["asc", "desc"] = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("contacts.read")),
) -> ContactListResponse:
    rows, total = await list_contacts(
        db,
        q=q,
        source=source,
        tag=tag,
        assigned_to_id=assigned_to_id,
        custom_filters=_extract_custom_filters(request),
        sort=sort,
        order=order,
        page=page,
        size=size,
    )
    return ContactListResponse(
        items=[ContactListItem.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post("", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
async def create_contact_endpoint(
    payload: ContactCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.write")),
) -> ContactOut:
    contact = await create_contact(db, org_id=user.org_id, payload=payload)
    return ContactOut.model_validate(contact)


@router.get("/{contact_id}", response_model=ContactOut)
async def get_contact_endpoint(
    contact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("contacts.read")),
) -> ContactOut:
    contact = await get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="contact not found"
        )
    return ContactOut.model_validate(contact)


@router.patch("/{contact_id}", response_model=ContactOut)
async def update_contact_endpoint(
    contact_id: uuid.UUID,
    payload: ContactUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("contacts.write")),
) -> ContactOut:
    contact = await update_contact(db, contact_id=contact_id, payload=payload)
    return ContactOut.model_validate(contact)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact_endpoint(
    contact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("contacts.write")),
) -> Response:
    await delete_contact(db, contact_id=contact_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Reassign + bulk-action endpoints ---------------------------------------


@router.post("/{contact_id}/reassign", response_model=ContactOut)
async def reassign_contact_endpoint(
    contact_id: uuid.UUID,
    payload: ContactReassign,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.reassign")),
) -> ContactOut:
    contact = await reassign_contact(
        db,
        contact_id=contact_id,
        org_id=user.org_id,
        assigned_to_id=payload.assigned_to_id,
        note=payload.note,
        actor_user_id=user.legacy_uuid,
    )
    return ContactOut.model_validate(contact)


@router.post("/bulk-reassign", response_model=ContactBulkReassignResult)
async def bulk_reassign_endpoint(
    payload: ContactBulkReassign,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.reassign")),
) -> ContactBulkReassignResult:
    n = await bulk_reassign_contacts(
        db,
        ids=payload.ids,
        org_id=user.org_id,
        assigned_to_id=payload.assigned_to_id,
        note=payload.note,
        actor_user_id=user.legacy_uuid,
    )
    return ContactBulkReassignResult(reassigned=n)


@router.post("/bulk-delete", response_model=ContactBulkDeleteResult)
async def bulk_delete_endpoint(
    payload: ContactBulkDelete,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.write")),
) -> ContactBulkDeleteResult:
    n = await bulk_delete_contacts(db, ids=payload.ids, org_id=user.org_id)
    return ContactBulkDeleteResult(deleted=n)


@router.post("/bulk-add-tag", response_model=ContactBulkAddTagResult)
async def bulk_add_tag_endpoint(
    payload: ContactBulkAddTag,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.write")),
) -> ContactBulkAddTagResult:
    n = await bulk_add_tag_contacts(
        db, ids=payload.ids, tag=payload.tag, org_id=user.org_id
    )
    return ContactBulkAddTagResult(updated=n)
