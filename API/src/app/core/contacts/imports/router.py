"""HTTP routes for the contact-imports surface.

  POST /api/v1/contacts/imports/upload         → multipart, returns import_id + mapping suggestion
  POST /api/v1/contacts/imports/{id}/dry-run   → count without writing
  POST /api/v1/contacts/imports/{id}/commit    → insert + optional group creation
  GET  /api/v1/contacts/imports/{id}/errors.csv → downloadable per-row error report

All endpoints gate on `contacts.write` — same key used by the
contacts create/edit endpoints. No new permission key.
"""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.contacts.imports.schemas import (
    ImportCommitIn,
    ImportCommitOut,
    ImportDryRunIn,
    ImportDryRunOut,
    ImportUploadOut,
)
from src.app.core.contacts.imports.service import (
    MAX_FILE_SIZE_BYTES,
    build_errors_csv_response,
    commit_import,
    dry_run_import,
    upload_file,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/contacts/imports", tags=["Contact Imports"])


@router.post("/upload", response_model=ImportUploadOut)
async def upload_endpoint(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.write")),
) -> ImportUploadOut:
    """Persist the uploaded file + return parsed headers, suggested
    mapping, and the first 5 sample rows for the mapping-step UI.
    413 if the file or row count exceeds the cap; 400 for unparseable
    files or unsupported extensions."""
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="filename missing",
        )
    # Streamed size check: read in chunks and 413 as soon as we cross
    # the cap. Prior behaviour was `await file.read()` which buffered
    # every byte in memory before the size check — a 500MB upload
    # spikes container RAM before the 413 fires.
    file_bytes = bytearray()
    while chunk := await file.read(1 << 20):  # 1 MiB chunks
        file_bytes.extend(chunk)
        if len(file_bytes) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds the {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB cap.",
            )
    return await upload_file(
        db,
        org_id=user.org_id,
        user_id=user.legacy_uuid,
        filename=file.filename,
        file_bytes=bytes(file_bytes),
    )


@router.post("/{import_id}/dry-run", response_model=ImportDryRunOut)
async def dry_run_endpoint(
    import_id: uuid.UUID,
    payload: ImportDryRunIn,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("contacts.write")),
) -> ImportDryRunOut:
    """Preview what `commit` would do — inserts/skips/dupe counts +
    per-row errors. Persists the dry-run snapshot on the import row so
    the operator can come back later and commit without rerunning."""
    return await dry_run_import(
        db,
        import_id=import_id,
        mapping=payload.mapping,
        opt_in_source=payload.opt_in_source,
    )


@router.post("/{import_id}/commit", response_model=ImportCommitOut)
async def commit_endpoint(
    import_id: uuid.UUID,
    payload: ImportCommitIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.write")),
) -> ImportCommitOut:
    """Insert the contacts. Optional `create_group=true` bundles the
    successfully-inserted rows into a new static contact group named
    `group_name`."""
    row = await commit_import(
        db,
        org_id=user.org_id,
        user_id=user.legacy_uuid,
        import_id=import_id,
        mapping=payload.mapping,
        create_group=payload.create_group,
        group_name=payload.group_name,
        opt_in_source=payload.opt_in_source,
    )
    return ImportCommitOut(
        id=row.id,
        status=row.status.value,
        row_count=row.row_count,
        success_count=row.success_count,
        error_count=row.error_count,
        created_group_id=row.created_group_id,
    )


@router.get("/{import_id}/errors.csv")
async def download_errors_csv_endpoint(
    import_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.write")),
) -> StreamingResponse:
    """Stream a CSV of every failed row from a completed import.

    Columns are the original file columns + `__row_number`, `__column`,
    `__value`, `__error_reason`. Available after dry-run or commit;
    contents match the operator's persisted `error_log` snapshot.
    """
    return await build_errors_csv_response(
        db,
        org_id=user.org_id,
        import_id=import_id,
    )
