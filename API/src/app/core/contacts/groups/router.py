"""HTTP routes for the contact-groups API surface.

  GET    /api/v1/contact-groups               → paginated list
  POST   /api/v1/contact-groups               → create
  GET    /api/v1/contact-groups/{id}          → detail (+ sample members)
  PATCH  /api/v1/contact-groups/{id}          → partial update
  DELETE /api/v1/contact-groups/{id}          → hard delete
  POST   /api/v1/contact-groups/preview-size  → count only

Permission model:
  - Reads (`GET`, `preview-size`) gate on `contacts.read`.
  - Writes (`POST`, `PATCH`, `DELETE`) gate on `contacts.write`.

Both keys exist on the `contacts` module from Phase 1, so this
surface adds no new permission registry entries.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.contacts.groups.schemas import (
    GroupCreate,
    GroupDetail,
    GroupListResponse,
    GroupRead,
    GroupUpdate,
    PreviewSizeIn,
    PreviewSizeOut,
)
from src.app.core.contacts.groups.service import (
    create_group,
    delete_group,
    get_group,
    get_member_count,
    get_sample_member_ids,
    list_groups,
    preview_audience_size,
    update_group,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/contact-groups", tags=["Contact Groups"])


@router.get("", response_model=GroupListResponse)
async def list_groups_endpoint(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("contacts.read")),
) -> GroupListResponse:
    """Paginated list with per-row `member_count` attached. The UI
    uses this to render the Groups table (Step 3.5.8)."""
    rows, total = await list_groups(db, page=page, size=size)
    items: list[GroupRead] = []
    for row in rows:
        count = await get_member_count(db, group=row)
        item = GroupRead.model_validate(row)
        item.member_count = count
        items.append(item)
    return GroupListResponse(items=items, total=total, page=page, size=size)


@router.post(
    "",
    response_model=GroupRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_group_endpoint(
    payload: GroupCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.write")),
) -> GroupRead:
    """Create a new contact group. Mode is set at creation and cannot
    be flipped later — delete + recreate is the explicit path."""
    row = await create_group(
        db,
        org_id=user.org_id,
        user_id=user.legacy_uuid,
        payload=payload,
    )
    out = GroupRead.model_validate(row)
    out.member_count = len(payload.contact_ids or []) if not payload.is_dynamic else None
    return out


@router.get("/{group_id}", response_model=GroupDetail)
async def get_group_endpoint(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("contacts.read")),
) -> GroupDetail:
    """Detail view — includes `member_count` + a sample of the first
    10 member contact IDs for the edit-page preview."""
    row = await get_group(db, group_id)
    count = await get_member_count(db, group=row)
    sample = await get_sample_member_ids(db, group=row)
    out = GroupDetail.model_validate(row)
    out.member_count = count
    out.sample_contact_ids = sample
    return out


@router.patch("/{group_id}", response_model=GroupRead)
async def update_group_endpoint(
    group_id: uuid.UUID,
    payload: GroupUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("contacts.write")),
) -> GroupRead:
    """Partial update — name/description always editable; filter or
    members replaceable depending on mode. Mode itself is immutable."""
    row = await update_group(db, group_id=group_id, payload=payload)
    count = await get_member_count(db, group=row)
    out = GroupRead.model_validate(row)
    out.member_count = count
    return out


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group_endpoint(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("contacts.write")),
) -> Response:
    """Hard delete. Bridge rows cascade. Campaigns referencing this
    group resolve to an empty audience after deletion (Step 3.5.9
    handles that gracefully)."""
    await delete_group(db, group_id=group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/preview-size", response_model=PreviewSizeOut)
async def preview_size_endpoint(
    payload: PreviewSizeIn,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("contacts.read")),
) -> PreviewSizeOut:
    """Count the contacts a filter or saved group would reach without
    materialising rows. Drives the live "X contacts will receive
    this" line in the Step 3.5.9 campaign audience builder."""
    count = await preview_audience_size(
        db,
        filter_json=payload.filter_json,
        group_id=payload.group_id,
    )
    return PreviewSizeOut(count=count)
