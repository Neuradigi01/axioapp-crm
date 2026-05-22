"""HTTP routes for the lead-imports sub-package.

  POST   /api/v1/leads/import/upload   → multipart upload, returns the
                                         freshly-created job row.
  GET    /api/v1/leads/import           → paginated list of imports
                                         (optional `status` filter).
  GET    /api/v1/leads/import/{id}     → one import row.

All endpoints gated by `leads.import`. The permission key is registered
through the leads module descriptor's `MODULE.permissions` list, so
the lifespan's `discover_modules()` sweep populates the row in the
`permissions` table at startup.
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
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.leads.imports.models import LeadImportStatus
from src.app.core.leads.imports.schemas import (
    LeadImportListResponse,
    LeadImportRead,
    SourcePlatform,
)
from src.app.core.leads.imports.service import (
    get_import,
    list_imports,
    upload,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/leads/import", tags=["Leads", "Bulk Import"])


@router.post(
    "/upload",
    response_model=LeadImportRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_lead_import_endpoint(
    file: UploadFile = File(...),
    source_platform: SourcePlatform = Form(...),
    name: Optional[str] = Form(default=None, max_length=255),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.import")),
) -> LeadImportRead:
    """Multipart upload of a CSV/XLSX lead export. Stores the raw file
    under `./storage/{org_id}/imports/{import_id}/source.<ext>` via
    the storage backend; creates the job row in `awaiting_mapping`.

    The Step 2 commit-mapping endpoint takes over from there; this
    endpoint never parses content beyond a cheap row-count estimate.
    """
    data = await file.read()
    row = await upload(
        db,
        org_id=user.org_id,
        uploader_id=user.legacy_uuid,
        data=data,
        filename=file.filename or "upload",
        content_type=file.content_type,
        source_platform=source_platform,
        name=name,
    )
    return LeadImportRead.model_validate(row)


@router.get("", response_model=LeadImportListResponse)
async def list_lead_imports_endpoint(
    status_filter: Optional[LeadImportStatus] = None,
    page: int = 1,
    size: int = 50,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("leads.import")),
) -> LeadImportListResponse:
    rows, total = await list_imports(
        db, status_filter=status_filter, page=page, size=size
    )
    return LeadImportListResponse(
        items=[LeadImportRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.get("/{import_id}", response_model=LeadImportRead)
async def get_lead_import_endpoint(
    import_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("leads.import")),
) -> LeadImportRead:
    row = await get_import(db, import_id)
    if row is None:
        # Either nonexistent or a foreign-org id (RLS-hidden). Surface
        # as 404 so we don't leak existence across tenants.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="import not found"
        )
    return LeadImportRead.model_validate(row)
