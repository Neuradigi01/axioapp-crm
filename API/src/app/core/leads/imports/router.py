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

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.leads.imports.models import LeadImportStatus
from src.app.core.leads.imports.presets import (
    create_preset,
    delete_preset,
    list_presets,
)
from src.app.core.leads.imports.schemas import (
    LeadImportCommit,
    LeadImportListResponse,
    LeadImportRead,
    MappingTarget,
    PresetCreate,
    PresetRead,
    PreviewResponse,
    SourcePlatform,
)
from src.app.core.leads.imports.service import (
    cancel_import,
    commit_mapping,
    get_import,
    list_imports,
    read_error_csv,
    read_preview,
    read_skipped_csv,
    read_source_file,
    read_warnings_csv,
    upload,
)
from src.app.core.leads.imports.targets import list_targets
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
    name: str | None = Form(default=None, max_length=255),
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
    status_filter: LeadImportStatus | None = None,
    source_platform: SourcePlatform | None = None,
    page: int = 1,
    size: int = 50,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("leads.import")),
) -> LeadImportListResponse:
    rows, total = await list_imports(
        db,
        status_filter=status_filter,
        source_platform=source_platform,
        page=page,
        size=size,
    )
    return LeadImportListResponse(
        items=[LeadImportRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.get("/targets", response_model=list[MappingTarget])
async def list_mapping_targets_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("leads.import")),
) -> list[MappingTarget]:
    """Return every CRM field a bulk-import row can map to.

    Combines the standard-fields registry (canonical contact + lead
    columns) with this org's `custom_field_definitions`. The mapping
    UI uses this to populate the per-CSV-column dropdown.
    """
    return await list_targets(db)


@router.get("/presets", response_model=list[PresetRead])
async def list_import_presets_endpoint(
    source_platform: SourcePlatform,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.import")),
) -> list[PresetRead]:
    """List system + org-owned mapping presets for one platform.

    System presets surface first; org-owned presets follow in
    most-recent-first order. The mapping UI picks the org's newest
    preset as the auto-default, falling back to the system row.
    """
    rows = await list_presets(db, org_id=user.org_id, source_platform=source_platform)
    return [PresetRead.model_validate(r) for r in rows]


@router.post(
    "/presets",
    response_model=PresetRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_import_preset_endpoint(
    payload: PresetCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.import")),
) -> PresetRead:
    """Save the current mapping as a reusable org-owned preset.

    Validates `mapping` against `/leads/import/targets`. Auto-names
    "<platform> vN" when `name` is omitted.
    """
    row = await create_preset(
        db,
        org_id=user.org_id,
        actor_id=user.legacy_uuid,
        name=payload.name,
        source_platform=payload.source_platform,
        mapping=payload.mapping,
    )
    return PresetRead.model_validate(row)


@router.delete("/presets/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_import_preset_endpoint(
    preset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.import")),
) -> Response:
    """Remove an org-owned preset. System presets reject with 403."""
    await delete_preset(
        db,
        org_id=user.org_id,
        actor_id=user.legacy_uuid,
        preset_id=preset_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="import not found")
    return LeadImportRead.model_validate(row)


@router.post("/{import_id}/commit", response_model=LeadImportRead)
async def commit_lead_import_endpoint(
    import_id: uuid.UUID,
    payload: LeadImportCommit,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.import")),
) -> LeadImportRead:
    """Validate + persist the mapping, transition to
    `mapping_committed`, queue the Celery processor. When
    `CELERY_ENABLED=false` (dev), the task runs synchronously inline,
    so the response may already reflect `completed` status."""
    row = await commit_mapping(
        db,
        import_id=import_id,
        mapping=payload.mapping,
        actor_id=user.legacy_uuid,
    )
    return LeadImportRead.model_validate(row)


@router.post("/{import_id}/cancel", response_model=LeadImportRead)
async def cancel_lead_import_endpoint(
    import_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.import")),
) -> LeadImportRead:
    row = await cancel_import(db, import_id=import_id, actor_id=user.legacy_uuid)
    return LeadImportRead.model_validate(row)


@router.get("/{import_id}/preview", response_model=PreviewResponse)
async def preview_lead_import_endpoint(
    import_id: uuid.UUID,
    limit: int = 5,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("leads.import")),
) -> PreviewResponse:
    """Return the first N data rows of an uploaded import file.

    Used by the mapping UI's preview pane. Header order is preserved
    so dropdowns line up with source columns one-to-one. `limit` is
    capped at 50 server-side.
    """
    row = await get_import(db, import_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="import not found")
    payload = await read_preview(row, limit)
    return PreviewResponse(columns=payload.columns, rows=payload.rows)


@router.get("/{import_id}/source")
async def download_import_source_endpoint(
    import_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("leads.import")),
) -> Response:
    """Stream the original uploaded source file.

    Used by the history page's "Download source" action so an op can
    re-inspect what was actually uploaded weeks ago. The browser is
    handed the file with the original filename via Content-Disposition.
    Permission + RLS scope to the caller's org; foreign-org id → 404.
    """
    row = await get_import(db, import_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="import not found")
    data = await read_source_file(row)
    safe_filename = (row.original_filename or "import.csv").replace('"', "")
    return Response(
        content=data,
        media_type=row.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
        },
    )


@router.get("/{import_id}/errors.csv")
async def download_import_errors_endpoint(
    import_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("leads.import")),
) -> Response:
    """Download the per-import error CSV produced by the processor.

    404 if the import has no errors (no file written) or if the import
    row is foreign-org / nonexistent (RLS-hidden).
    """
    row = await get_import(db, import_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="import not found")
    data = await read_error_csv(row)
    filename = f"import-{import_id}-errors.csv"
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{import_id}/skipped.csv")
async def download_import_skipped_endpoint(
    import_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("leads.import")),
) -> Response:
    """Download the per-import "duplicates skipped" CSV.

    Contains one row per input row where dedup collapsed the new lead
    into an existing open lead. Each row carries the original columns
    plus four inspection columns: ``__row_number``,
    ``__contact_match_reason``, ``__matched_contact_id``,
    ``__merged_into_lead_id``.

    404 if the import didn't skip anything (no file written) or the
    row is foreign-org / nonexistent.
    """
    row = await get_import(db, import_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="import not found")
    data = await read_skipped_csv(row)
    filename = f"import-{import_id}-skipped.csv"
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{import_id}/warnings.csv")
async def download_import_warnings_endpoint(
    import_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("leads.import")),
) -> Response:
    """Download the per-import warnings CSV.

    Contains one row per input row that was imported successfully
    but only after substituting an out-of-vocabulary value (currently:
    an unknown ``pipeline_stage`` falling back to the pipeline's
    default first stage). Each row carries the original columns plus
    the ``__original_value`` / ``__substituted_value`` /
    ``__created_lead_id`` / ``__created_contact_id`` inspection
    columns so operators can bulk-edit the substituted stages later.

    404 if the import emitted no warnings.
    """
    row = await get_import(db, import_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="import not found")
    data = await read_warnings_csv(row)
    filename = f"import-{import_id}-warnings.csv"
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
