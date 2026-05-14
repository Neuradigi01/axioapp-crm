"""HTTP routes for the furniture-pack field-ops module.

Two route trees:

  Admin (JWT + permission gates):
    /api/v1/field-visits                          (CRUD + filters)
    /api/v1/field-visits/{id}/complete            (POST)
    /api/v1/field-visits/{id}/photos              (GET/POST multipart)

  Staff portal (staff-token bearer, scope='staff'):
    /api/v1/staff-portal/me/field-visits          (GET — assigned-to-me)
    /api/v1/staff-portal/me/field-visits/{id}/complete   (POST)
    /api/v1/staff-portal/me/field-visits/{id}/photos     (GET/POST multipart)

The staff-portal subset never lets a staff user create or delete visits
— scheduling happens from the admin app. They can only see their own
queue and close visits they've finished.

Permissions:
  - `field_visits.read`  → admin GETs
  - `field_visits.write` → admin create/update/delete/complete/photos
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import (
    get_current_staff,
    require_permissions,
)
from src.app.core.users.models import User
from src.app.packs.furniture.modules.field_ops.models import FieldVisitPurpose
from src.app.packs.furniture.modules.field_ops.schemas import (
    FieldVisitCompletePayload,
    FieldVisitCreate,
    FieldVisitListResponse,
    FieldVisitOut,
    FieldVisitPhotoOut,
    FieldVisitUpdate,
)
from src.app.packs.furniture.modules.field_ops.service import (
    add_photo,
    complete_visit,
    create_visit,
    delete_visit,
    get_visit,
    list_photos,
    list_visits,
    update_visit,
)
from src.app.shared.db import get_db


# --- admin router -------------------------------------------------------


router = APIRouter(prefix="/field-visits", tags=["Field Visits"])


@router.get("", response_model=FieldVisitListResponse)
async def list_visits_endpoint(
    assigned_to_id: Optional[uuid.UUID] = Query(default=None),
    purpose: Optional[FieldVisitPurpose] = Query(default=None),
    completed: Optional[bool] = Query(default=None),
    custom_order_id: Optional[uuid.UUID] = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("field_visits.read")),
) -> FieldVisitListResponse:
    rows, total = await list_visits(
        db,
        assigned_to_id=assigned_to_id,
        purpose=purpose,
        completed=completed,
        custom_order_id=custom_order_id,
        page=page,
        size=size,
    )
    return FieldVisitListResponse(
        items=[FieldVisitOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post(
    "",
    response_model=FieldVisitOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_visit_endpoint(
    payload: FieldVisitCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("field_visits.write")),
) -> FieldVisitOut:
    visit = await create_visit(
        db, org_id=user.org_id, user_id=user.id, payload=payload
    )
    return FieldVisitOut.model_validate(visit)


@router.get("/{visit_id}", response_model=FieldVisitOut)
async def get_visit_endpoint(
    visit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("field_visits.read")),
) -> FieldVisitOut:
    visit = await get_visit(db, visit_id)
    return FieldVisitOut.model_validate(visit)


@router.patch("/{visit_id}", response_model=FieldVisitOut)
async def update_visit_endpoint(
    visit_id: uuid.UUID,
    payload: FieldVisitUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("field_visits.write")),
) -> FieldVisitOut:
    visit = await update_visit(db, visit_id=visit_id, payload=payload)
    return FieldVisitOut.model_validate(visit)


@router.delete("/{visit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_visit_endpoint(
    visit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("field_visits.write")),
) -> Response:
    await delete_visit(db, visit_id=visit_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{visit_id}/complete", response_model=FieldVisitOut)
async def complete_visit_endpoint(
    visit_id: uuid.UUID,
    payload: FieldVisitCompletePayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("field_visits.write")),
) -> FieldVisitOut:
    visit = await complete_visit(
        db, visit_id=visit_id, user_id=user.id, payload=payload
    )
    return FieldVisitOut.model_validate(visit)


@router.get(
    "/{visit_id}/photos", response_model=list[FieldVisitPhotoOut]
)
async def list_photos_endpoint(
    visit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("field_visits.read")),
) -> list[FieldVisitPhotoOut]:
    await get_visit(db, visit_id)
    rows = await list_photos(db, visit_id=visit_id)
    return [FieldVisitPhotoOut.model_validate(r) for r in rows]


@router.post(
    "/{visit_id}/photos",
    response_model=FieldVisitPhotoOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_photo_endpoint(
    visit_id: uuid.UUID,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("field_visits.write")),
) -> FieldVisitPhotoOut:
    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="uploaded file is empty",
        )
    ext = "jpg"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()[:8]
    photo = await add_photo(
        db,
        visit_id=visit_id,
        data=data,
        content_type=file.content_type or "application/octet-stream",
        file_extension=ext,
        caption=caption,
    )
    return FieldVisitPhotoOut.model_validate(photo)


# --- staff portal router -----------------------------------------------


staff_portal_router = APIRouter(
    prefix="/staff-portal/me/field-visits", tags=["StaffPortal"]
)


@staff_portal_router.get("", response_model=list[FieldVisitOut])
async def me_list_visits_endpoint(
    completed: Optional[bool] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_staff),
) -> list[FieldVisitOut]:
    rows, _total = await list_visits(
        db,
        assigned_to_id=user.id,
        completed=completed,
        page=1,
        size=200,
    )
    return [FieldVisitOut.model_validate(r) for r in rows]


@staff_portal_router.get(
    "/{visit_id}", response_model=FieldVisitOut
)
async def me_get_visit_endpoint(
    visit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_staff),
) -> FieldVisitOut:
    visit = await get_visit(db, visit_id)
    return FieldVisitOut.model_validate(visit)


@staff_portal_router.post(
    "/{visit_id}/complete", response_model=FieldVisitOut
)
async def me_complete_visit_endpoint(
    visit_id: uuid.UUID,
    payload: FieldVisitCompletePayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_staff),
) -> FieldVisitOut:
    visit = await complete_visit(
        db, visit_id=visit_id, user_id=user.id, payload=payload
    )
    return FieldVisitOut.model_validate(visit)


@staff_portal_router.get(
    "/{visit_id}/photos", response_model=list[FieldVisitPhotoOut]
)
async def me_list_photos_endpoint(
    visit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_staff),
) -> list[FieldVisitPhotoOut]:
    await get_visit(db, visit_id)
    rows = await list_photos(db, visit_id=visit_id)
    return [FieldVisitPhotoOut.model_validate(r) for r in rows]


@staff_portal_router.post(
    "/{visit_id}/photos",
    response_model=FieldVisitPhotoOut,
    status_code=status.HTTP_201_CREATED,
)
async def me_upload_photo_endpoint(
    visit_id: uuid.UUID,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(default=None),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_staff),
) -> FieldVisitPhotoOut:
    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="uploaded file is empty",
        )
    ext = "jpg"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()[:8]
    photo = await add_photo(
        db,
        visit_id=visit_id,
        data=data,
        content_type=file.content_type or "application/octet-stream",
        file_extension=ext,
        caption=caption,
    )
    return FieldVisitPhotoOut.model_validate(photo)
