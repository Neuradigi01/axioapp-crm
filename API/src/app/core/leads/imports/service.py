"""Service layer for the lead-imports sub-package.

`upload()` is the one write path Step 1 ships. It validates the file
(mimetype, size cap, row-count estimate), persists the raw bytes via
the storage backend at `{org_id}/imports/{import_id}/source.{ext}`,
inserts the `LeadImport` row in `awaiting_mapping`, and emits a
`lead_imports.started` audit row. No parsing, mapping, or dedup —
those live in Step 2's Celery task.

The row-count estimate uses a cheap line-count for CSV (good enough
to gate the 50k cap) and the openpyxl read-only sheet's `max_row` for
XLSX. Both fail closed: if a file can't be parsed enough to count
rows, the upload is rejected.

`get_import` and `list_imports` are pure reads, tenant-scoped by the
ORM filter so each org sees only its own imports.
"""
from __future__ import annotations

import csv
import io
import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.leads.imports.models import LeadImport, LeadImportStatus
from src.app.core.leads.imports.schemas import SourcePlatform
from src.app.shared.storage import get_storage


# 10 MB cap on uploaded file size; 50,000 rows on parsed row count.
# Both are bulk-import track invariants — bigger imports should be
# chunked or escalated to a one-off DB-side bulk insert, not run
# through this endpoint.
_MAX_BYTES = 10 * 1024 * 1024
_MAX_ROWS = 50_000

_ALLOWED_CSV_MIMES = {"text/csv", "application/csv", "text/plain"}
_ALLOWED_XLSX_MIMES = {
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",  # browsers sometimes send this for .xlsx
}


def _classify(filename: Optional[str], mime: Optional[str]) -> tuple[str, str]:
    """Return (kind, ext) for a CSV/XLSX upload. Raises 415 otherwise.

    `kind` is one of {"csv", "xlsx"}; `ext` is the lowercase extension
    we'll use when writing the file to disk.
    """
    name = (filename or "").lower()
    mime_normalised = (mime or "").lower()

    if name.endswith(".csv") or mime_normalised in _ALLOWED_CSV_MIMES:
        return "csv", "csv"
    if name.endswith(".xlsx") or mime_normalised in _ALLOWED_XLSX_MIMES:
        return "xlsx", "xlsx"
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail=(
            "Only CSV (.csv) and Excel (.xlsx) files are accepted. "
            f"Got filename={filename!r}, content-type={mime!r}."
        ),
    )


def _estimate_csv_rows(data: bytes) -> int:
    """Count data rows in a CSV (excludes the header). Tolerant of
    quoted newlines via `csv.reader` so a multi-line cell doesn't get
    over-counted as separate rows.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Fall back to latin-1; CSV exports from old systems aren't
        # always UTF-8. We don't need exact char-level accuracy for a
        # row count, only newline boundaries.
        text = data.decode("latin-1", errors="ignore")
    reader = csv.reader(io.StringIO(text))
    count = 0
    for i, _ in enumerate(reader):
        if i == 0:
            continue  # header
        count += 1
    return count


def _estimate_xlsx_rows(data: bytes) -> int:
    """Open the first sheet read-only and return its data row count
    (excludes the header row). Uses openpyxl which is already a
    transitive dep elsewhere in the project.
    """
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - openpyxl is bundled
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="XLSX parser not installed",
        ) from exc

    try:
        wb = load_workbook(filename=io.BytesIO(data), read_only=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not parse Excel file: {exc}",
        ) from exc
    try:
        ws = wb.active
        if ws is None or ws.max_row is None:
            return 0
        return max(0, ws.max_row - 1)
    finally:
        wb.close()


async def upload(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    uploader_id: uuid.UUID,
    data: bytes,
    filename: str,
    content_type: Optional[str],
    source_platform: SourcePlatform,
    name: Optional[str],
) -> LeadImport:
    """Persist a freshly-uploaded import file + create its job row."""
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )
    if len(data) > _MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"File exceeds {_MAX_BYTES // (1024 * 1024)} MB cap "
                f"(got {len(data)} bytes)."
            ),
        )

    kind, ext = _classify(filename, content_type)
    row_count = (
        _estimate_csv_rows(data) if kind == "csv" else _estimate_xlsx_rows(data)
    )
    if row_count > _MAX_ROWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"File contains {row_count} rows; the per-import cap is "
                f"{_MAX_ROWS:,}. Split the file and try again."
            ),
        )

    import_id = uuid.uuid4()
    storage_path = f"{org_id}/imports/{import_id}/source.{ext}"
    get_storage().put(
        storage_path,
        data,
        content_type=content_type or "application/octet-stream",
    )

    label = name or f"{source_platform} import — {filename}"
    row = LeadImport(
        id=import_id,
        org_id=org_id,
        uploaded_by=uploader_id,
        name=label,
        source_platform=source_platform,
        original_filename=filename,
        storage_path=storage_path,
        byte_size=len(data),
        row_count_estimate=row_count,
        mime_type=content_type or "application/octet-stream",
        status=LeadImportStatus.awaiting_mapping,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    await audit.log(
        "lead_imports.started",
        entity_type="lead_import",
        entity_id=row.id,
        after={
            "import_id": str(row.id),
            "source_platform": row.source_platform,
            "filename": row.original_filename,
            "byte_size": row.byte_size,
            "row_count_estimate": row.row_count_estimate,
        },
    )
    return row


async def get_import(
    session: AsyncSession, import_id: uuid.UUID
) -> Optional[LeadImport]:
    """Fetch one import row. Tenant filter scopes to the caller's org —
    a foreign-org id surfaces as None (the router maps that to 404).
    """
    return (
        await session.execute(
            select(LeadImport).where(LeadImport.id == import_id)
        )
    ).scalar_one_or_none()


async def list_imports(
    session: AsyncSession,
    *,
    status_filter: Optional[LeadImportStatus] = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[LeadImport], int]:
    """Paginated list of imports for the caller's org.

    Future status / source-platform filters land in Step 6 when the
    history page wants them. For now the optional `status_filter` is
    the only narrowing — keeps the surface tiny.
    """
    base = select(LeadImport)
    count_stmt = select(func.count()).select_from(LeadImport)
    if status_filter is not None:
        base = base.where(LeadImport.status == status_filter)
        count_stmt = count_stmt.where(LeadImport.status == status_filter)
    base = base.order_by(LeadImport.created_at.desc(), LeadImport.id.desc())

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(base.offset((page - 1) * size).limit(size))
    ).scalars().all()
    return list(rows), int(total)


__all__ = ["get_import", "list_imports", "upload"]
