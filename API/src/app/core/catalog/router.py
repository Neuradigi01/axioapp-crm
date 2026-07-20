"""HTTP routes for the catalog module.

Items:
  GET    /api/v1/catalog?q=&category=&category_id=&active_only=&page=&size=
  POST   /api/v1/catalog
  GET    /api/v1/catalog/categories                (list)
  POST   /api/v1/catalog/categories                (create)
  PATCH  /api/v1/catalog/categories/{id}           (update)
  DELETE /api/v1/catalog/categories/{id}
  POST   /api/v1/catalog/bulk-import               (dry-run or commit)
  GET    /api/v1/catalog/{id}
  PATCH  /api/v1/catalog/{id}
  DELETE /api/v1/catalog/{id}
  POST   /api/v1/catalog/{id}/image                (primary cover — multipart)
  POST   /api/v1/catalog/{id}/images               (gallery add — multipart)
  DELETE /api/v1/catalog/{id}/images?index=N       (gallery remove)

Reads need `catalog.read`; writes need `catalog.write`. Tenant scoping
is automatic via the ORM filter on `TenantScoped`.

Static-segment routes (``/categories``, ``/bulk-import``) are declared
BEFORE the dynamic ``/{item_id}`` capture so FastAPI doesn't try to
parse those as UUIDs (a 422 trap seen with several other modules).
"""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.catalog.schemas import (
    CatalogCategoryCreate,
    CatalogCategoryOut,
    CatalogCategoryUpdate,
    CatalogItemBulkImportRequest,
    CatalogItemBulkImportResult,
    CatalogItemCreate,
    CatalogItemOut,
    CatalogItemUpdate,
    CatalogListResponse,
)
from src.app.core.catalog.service import (
    add_gallery_image,
    bulk_import_items,
    create_category,
    create_item,
    delete_category,
    delete_item,
    get_item,
    list_categories,
    list_items,
    remove_gallery_image,
    set_item_image,
    update_category,
    update_item,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/catalog", tags=["Catalog"])


# --- Categories (declared before /{item_id} for static-segment match) ------


@router.get("/categories", response_model=list[CatalogCategoryOut])
async def list_categories_endpoint(
    active_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("catalog.read")),
) -> list[CatalogCategoryOut]:
    rows = await list_categories(db, org_id=user.org_id, active_only=active_only)
    return [CatalogCategoryOut.model_validate(r) for r in rows]


@router.post(
    "/categories",
    response_model=CatalogCategoryOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_category_endpoint(
    payload: CatalogCategoryCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("catalog.write")),
) -> CatalogCategoryOut:
    cat = await create_category(db, org_id=user.org_id, payload=payload)
    return CatalogCategoryOut.model_validate(cat)


@router.patch("/categories/{category_id}", response_model=CatalogCategoryOut)
async def update_category_endpoint(
    category_id: uuid.UUID,
    payload: CatalogCategoryUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("catalog.write")),
) -> CatalogCategoryOut:
    cat = await update_category(db, category_id=category_id, payload=payload)
    return CatalogCategoryOut.model_validate(cat)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category_endpoint(
    category_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("catalog.write")),
) -> Response:
    await delete_category(db, category_id=category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Bulk import (declared before /{item_id}) -----------------------------


@router.post("/bulk-import", response_model=CatalogItemBulkImportResult)
async def bulk_import_endpoint(
    payload: CatalogItemBulkImportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("catalog.write")),
) -> CatalogItemBulkImportResult:
    """Bulk-insert catalog rows. Set ``dry_run=true`` for the wizard's
    preview step; the response reports would-insert / would-skip
    counts without committing."""
    return await bulk_import_items(db, org_id=user.org_id, payload=payload)


# --- Item CRUD ------------------------------------------------------------


@router.get("", response_model=CatalogListResponse)
async def list_items_endpoint(
    q: str | None = Query(default=None, max_length=255),
    category: str | None = Query(default=None, max_length=64),
    category_id: uuid.UUID | None = Query(default=None),
    active_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("catalog.read")),
) -> CatalogListResponse:
    rows, total = await list_items(
        db,
        q=q,
        category=category,
        category_id=category_id,
        active_only=active_only,
        page=page,
        size=size,
    )
    return CatalogListResponse(
        items=[CatalogItemOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post("", response_model=CatalogItemOut, status_code=status.HTTP_201_CREATED)
async def create_item_endpoint(
    payload: CatalogItemCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("catalog.write")),
) -> CatalogItemOut:
    item = await create_item(db, org_id=user.org_id, payload=payload)
    return CatalogItemOut.model_validate(item)


@router.get("/{item_id}", response_model=CatalogItemOut)
async def get_item_endpoint(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("catalog.read")),
) -> CatalogItemOut:
    item = await get_item(db, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="catalog item not found",
        )
    return CatalogItemOut.model_validate(item)


@router.patch("/{item_id}", response_model=CatalogItemOut)
async def update_item_endpoint(
    item_id: uuid.UUID,
    payload: CatalogItemUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("catalog.write")),
) -> CatalogItemOut:
    item = await update_item(db, item_id=item_id, payload=payload)
    return CatalogItemOut.model_validate(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item_endpoint(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("catalog.write")),
) -> Response:
    await delete_item(db, item_id=item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{item_id}/image", response_model=CatalogItemOut)
async def upload_item_image_endpoint(
    item_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("catalog.write")),
) -> CatalogItemOut:
    """Upload (or replace) the primary cover image for a catalog item.

    libmagic validates the real MIME — filename and Content-Type from
    the client are not trusted. Re-uploading swaps the file at the
    same storage path; if the detected extension changes the old file
    is deleted first (C1 correlate)."""
    file_bytes = await file.read()
    item = await set_item_image(db, org_id=user.org_id, item_id=item_id, file_bytes=file_bytes)
    return CatalogItemOut.model_validate(item)


# --- Gallery (C5) ---------------------------------------------------------


@router.post("/{item_id}/images", response_model=CatalogItemOut)
async def add_gallery_image_endpoint(
    item_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("catalog.write")),
) -> CatalogItemOut:
    """Append a new image to the item's gallery. Separate from the
    primary cover (``POST /image``) — gallery has a cap enforced at
    the service layer."""
    file_bytes = await file.read()
    item = await add_gallery_image(
        db, org_id=user.org_id, item_id=item_id, file_bytes=file_bytes
    )
    return CatalogItemOut.model_validate(item)


@router.delete("/{item_id}/images", response_model=CatalogItemOut)
async def remove_gallery_image_endpoint(
    item_id: uuid.UUID,
    index: int = Query(..., ge=0),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("catalog.write")),
) -> CatalogItemOut:
    """Remove the gallery image at ``index`` (0-based). Deletes the
    stored file too. Returns the updated item so the FE can re-render
    the strip without re-fetching."""
    item = await remove_gallery_image(db, item_id=item_id, index=index)
    return CatalogItemOut.model_validate(item)
