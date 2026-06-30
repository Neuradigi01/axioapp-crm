"""HTTP routes for `saved_views`.

  GET    /api/v1/saved-views?entity=<entity>  → list owned + shared
  POST   /api/v1/saved-views                  → create
  PATCH  /api/v1/saved-views/{id}             → owner-only update
  DELETE /api/v1/saved-views/{id}             → owner-only delete

All routes gated by ``saved_views.use`` — a productivity permission
granted to every authenticated user via the module's default permission
template (not a privilege). Owner-only checks for mutation live in the
service layer so the router stays declarative.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.saved_views.schemas import (
    SavedViewCreate,
    SavedViewOut,
    SavedViewUpdate,
)
from src.app.core.saved_views.service import (
    create_view,
    delete_view,
    list_views,
    update_view,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/saved-views", tags=["Saved Views"])


@router.get("", response_model=list[SavedViewOut])
async def list_saved_views_endpoint(
    entity: Literal["leads"] = Query(default="leads"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("saved_views.use")),
) -> list[SavedViewOut]:
    """All saved views the caller can see for `entity`.

    Owned first, then shared, alphabetical within each bucket. The FE
    relies on this ordering to render the "Mine / Shared" sections of
    the menu without re-sorting client-side.
    """
    views = await list_views(
        db,
        org_id=user.org_id,
        user_id=user.legacy_uuid,
        entity=entity,
    )
    return [SavedViewOut.model_validate(v) for v in views]


@router.post(
    "",
    response_model=SavedViewOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_saved_view_endpoint(
    payload: SavedViewCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("saved_views.use")),
) -> SavedViewOut:
    view = await create_view(
        db,
        org_id=user.org_id,
        user_id=user.legacy_uuid,
        payload=payload,
    )
    return SavedViewOut.model_validate(view)


@router.patch("/{view_id}", response_model=SavedViewOut)
async def update_saved_view_endpoint(
    view_id: uuid.UUID,
    payload: SavedViewUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("saved_views.use")),
) -> SavedViewOut:
    view = await update_view(
        db,
        view_id=view_id,
        user_id=user.legacy_uuid,
        payload=payload,
    )
    return SavedViewOut.model_validate(view)


@router.delete("/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_view_endpoint(
    view_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("saved_views.use")),
) -> Response:
    await delete_view(db, view_id=view_id, user_id=user.legacy_uuid)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
