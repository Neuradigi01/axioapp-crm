"""HTTP routes for the contact-imports surface.

  POST /api/v1/contacts/imports/upload         → multipart, returns import_id + mapping suggestion
  POST /api/v1/contacts/imports/{id}/dry-run   → count without writing
  POST /api/v1/contacts/imports/{id}/commit    → insert + optional group creation

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
    file_bytes = await file.read()
    return await upload_file(
        db,
        org_id=user.org_id,
        user_id=user.legacy_uuid,
        filename=file.filename,
        file_bytes=file_bytes,
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
    )
    return ImportCommitOut(
        id=row.id,
        status=row.status.value,
        row_count=row.row_count,
        success_count=row.success_count,
        error_count=row.error_count,
        created_group_id=row.created_group_id,
    )
