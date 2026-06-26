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
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.leads.imports import data_access
from src.app.core.leads.imports.models import LeadImport, LeadImportStatus
from src.app.core.leads.imports.schemas import SourcePlatform
from src.app.shared.storage import get_storage


# Whitelist of CRM field keys a mapping may target. System-managed
# columns (`id`, `org_id`, `source`, `status`, `created_at`,
# `updated_at`) are deliberately excluded — they're either auto-set
# (source='bulk_import', server timestamps) or org-scoped invariants
# (org_id, id). `custom_data.<key>` targets are allowed dynamically
# against the org's `custom_field_definitions`.
_ALLOWED_STANDARD_TARGETS: frozenset[str] = frozenset(
    {
        "contact.full_name",
        "contact.phone",
        "contact.email",
        "contact.source",
        "contact.notes",
        "lead.pipeline_stage",
        "lead.budget",
        "lead.expected_close_date",
    }
)

_REQUIRED_TARGETS: frozenset[str] = frozenset({"contact.full_name"})


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
    row = data_access.add_import(
        session,
        LeadImport(
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
        ),
    )
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
    return await data_access.get_import_by_id(session, import_id)


async def list_imports(
    session: AsyncSession,
    *,
    status_filter: Optional[LeadImportStatus] = None,
    source_platform: Optional[str] = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[LeadImport], int]:
    """Paginated list of imports for the caller's org.

    `status_filter` narrows to one lifecycle state; `source_platform`
    narrows to one source CRM. Both feed the Step 6 history page's
    filter controls. Tenant filter is automatic via `TenantScoped`.
    """
    total = await data_access.count_imports_filtered(
        session,
        status_filter=status_filter,
        source_platform=source_platform,
    )
    rows = await data_access.list_imports_page(
        session,
        status_filter=status_filter,
        source_platform=source_platform,
        offset=(page - 1) * size,
        limit=size,
    )
    return rows, total


def read_source_file(import_row: LeadImport) -> bytes:
    """Read the bytes of the original uploaded source file.

    Used by the Step 6 history page's "Download source" action so an
    op can re-inspect what was actually uploaded weeks ago. Raises 404
    if the file is missing from disk (e.g. retention cleanup).
    """
    from pathlib import Path

    full = Path("./storage").resolve() / import_row.storage_path.lstrip("/")
    if not full.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="source file missing on disk",
        )
    return full.read_bytes()


async def _allowed_custom_targets(session: AsyncSession) -> set[str]:
    """Return `custom_data.<key>` targets allowed for this org.

    Pulls every `custom_field_definitions` row for entity_type='lead'
    or 'contact' and emits `custom_data.<field_key>` for each. The
    ORM filter scopes to the active org automatically.
    """
    keys = await data_access.list_custom_field_keys(session)
    return {f"custom_data.{k}" for k in keys}


async def commit_mapping(
    session: AsyncSession,
    *,
    import_id: uuid.UUID,
    mapping: dict[str, Optional[str]],
    actor_id: uuid.UUID,
) -> LeadImport:
    """Validate + persist a mapping, transition to `mapping_committed`,
    queue the Celery processor. Raises:

    - 404 if the import doesn't exist (or is foreign-org, RLS-hidden).
    - 409 if the import isn't in `awaiting_mapping`.
    - 422 if the mapping targets are invalid (system-managed targets,
      unknown custom fields, missing the required full_name target).
    """
    row = await data_access.get_import_by_id(session, import_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="import not found"
        )
    if row.status != LeadImportStatus.awaiting_mapping:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot commit mapping: import is in '{row.status.value}'. "
                "Only 'awaiting_mapping' imports can be committed."
            ),
        )

    allowed = set(_ALLOWED_STANDARD_TARGETS)
    allowed |= await _allowed_custom_targets(session)

    targets = [v for v in mapping.values() if v]
    unknown = [t for t in targets if t not in allowed]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Mapping references unknown or forbidden targets: "
                f"{sorted(set(unknown))}. Allowed standard targets: "
                f"{sorted(_ALLOWED_STANDARD_TARGETS)}. Custom-field "
                "targets must be of the form custom_data.<key> and the "
                "field definition must exist for entity 'contact' or 'lead'."
            ),
        )

    missing_required = [t for t in _REQUIRED_TARGETS if t not in targets]
    if missing_required:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Mapping is missing required target(s): "
                f"{sorted(missing_required)}. Map at least one CSV column "
                "to 'contact.full_name' before committing."
            ),
        )

    row.mapping = mapping
    row.status = LeadImportStatus.mapping_committed
    await session.commit()
    await session.refresh(row)

    # Dispatch the processor. With Celery installed we enqueue and
    # return — the worker picks it up and the row transitions to
    # `processing` then `completed` asynchronously. Without Celery
    # (dev), we await the async body inline on the current event loop
    # so the response reflects the final status. Either way the row's
    # mapping is already persisted before this returns.
    from src.app.core.leads.imports.tasks import (
        HAS_CELERY,
        process_lead_import,
        process_lead_import_async,
    )

    if HAS_CELERY:
        process_lead_import.delay(str(row.id))
    else:
        await process_lead_import_async(row.id)
        await session.refresh(row)
    return row


async def cancel_import(
    session: AsyncSession,
    *,
    import_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> LeadImport:
    """User-driven cancel. Allowed only from `awaiting_mapping` or
    `mapping_committed` — once `processing` we don't kill the worker;
    once terminal there's nothing to do."""
    row = await data_access.get_import_by_id(session, import_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="import not found"
        )
    if row.status not in (
        LeadImportStatus.awaiting_mapping,
        LeadImportStatus.mapping_committed,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot cancel: import is in '{row.status.value}'. "
                "Cancel only works while awaiting mapping or pre-processing."
            ),
        )
    row.status = LeadImportStatus.cancelled
    await session.commit()
    await session.refresh(row)
    return row


def read_preview(import_row: LeadImport, limit: int) -> "PreviewPayload":
    """Read the first `limit` data rows from the import's source file.

    Returns the original column header + a list-of-lists of stringified
    cell values. The mapping UI uses this to populate the preview pane
    so the user can see how their mapping projects onto real data
    before committing.

    Reuses `parser.parse_rows()` with an empty mapping — only the
    `raw` dict is needed (one entry per source column). Rows are
    returned in source column order; missing cells surface as None.
    """
    from src.app.core.leads.imports.parser import parse_rows

    capped_limit = max(1, min(int(limit), 50))
    header, rows_iter = parse_rows(import_row.storage_path, mapping={})

    rows: list[list[Optional[str]]] = []
    for parsed in rows_iter:
        if len(rows) >= capped_limit:
            break
        rows.append([parsed.raw.get(col) for col in header.columns])

    return PreviewPayload(columns=header.columns, rows=rows)


@dataclass(frozen=True, slots=True)
class PreviewPayload:
    """Plain-Python projection of `read_preview` so the router can
    convert to the Pydantic `PreviewResponse` without leaking the
    parser internals."""

    columns: list[str]
    rows: list[list[Optional[str]]]


def read_error_csv(import_row: LeadImport) -> bytes:
    """Read the errors CSV bytes for a completed import.

    Raises 404 if the row has no `error_report_path` (no errors, or
    not yet processed). Storage is local-disk for v1; we read directly
    rather than streaming since the file is bounded by the per-import
    row cap (50k rows ⇒ a few MB worst case).
    """
    if not import_row.error_report_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="this import has no error report",
        )
    from pathlib import Path

    full = Path("./storage").resolve() / import_row.error_report_path.lstrip("/")
    if not full.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="error report file missing on disk",
        )
    return full.read_bytes()


__all__ = [
    "PreviewPayload",
    "cancel_import",
    "commit_mapping",
    "get_import",
    "list_imports",
    "read_error_csv",
    "read_preview",
    "read_source_file",
    "upload",
]
