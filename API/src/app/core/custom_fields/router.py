"""HTTP routes for `custom_field_definitions`.

Routes mounted under `/api/v1/custom-fields`. Reads require
`custom_fields.read`; mutations require `custom_fields.write`. Tenant
scoping is automatic via the `do_orm_execute` ORM filter.

  GET    /custom-fields?entity_type=&include_hidden=
  POST   /custom-fields                      → always creates source=user
  PATCH  /custom-fields/{id}                 → respects source rules
  DELETE /custom-fields/{id}                 → only source=user
  GET    /custom-fields/{entity_type}/render → visible + ordered for forms
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.custom_fields.schemas import (
    CustomFieldCreate,
    CustomFieldOut,
    CustomFieldRenderItem,
    CustomFieldUpdate,
)
from src.app.core.custom_fields.service import (
    create_user_field,
    delete_field,
    list_fields,
    render_fields,
    update_field,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/custom-fields", tags=["Custom Fields"])


@router.get("", response_model=list[CustomFieldOut])
async def list_custom_fields(
    entity_type: str = Query(..., min_length=1, max_length=64),
    include_hidden: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("custom_fields.read")),
) -> list[CustomFieldOut]:
    rows = await list_fields(db, entity_type=entity_type, include_hidden=include_hidden)
    return [CustomFieldOut.model_validate(row) for row in rows]


@router.post("", response_model=CustomFieldOut, status_code=status.HTTP_201_CREATED)
async def create_custom_field(
    payload: CustomFieldCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("custom_fields.write")),
) -> CustomFieldOut:
    field = await create_user_field(db, org_id=user.org_id, payload=payload)
    return CustomFieldOut.model_validate(field)


@router.patch("/{field_id}", response_model=CustomFieldOut)
async def update_custom_field(
    field_id: uuid.UUID,
    payload: CustomFieldUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("custom_fields.write")),
) -> CustomFieldOut:
    field = await update_field(db, field_id=field_id, payload=payload)
    return CustomFieldOut.model_validate(field)


@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_field(
    field_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("custom_fields.write")),
) -> Response:
    await delete_field(db, field_id=field_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{entity_type}/render",
    response_model=list[CustomFieldRenderItem],
)
async def render_custom_fields(
    entity_type: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("custom_fields.read")),
) -> list[CustomFieldRenderItem]:
    rows = await render_fields(db, entity_type=entity_type)
    return [CustomFieldRenderItem.model_validate(row) for row in rows]
