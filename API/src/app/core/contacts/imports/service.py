"""Service layer for contact bulk imports — upload, dry-run, commit."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.contacts.groups.models import (
    ContactGroup,
    ContactGroupMember,
)
from src.app.core.contacts.imports.models import (
    ContactImport,
    ContactImportStatus,
)
from src.app.core.contacts.imports.parser import (
    parse_all_rows,
    parse_headers_and_sample,
    suggest_mapping,
)
from src.app.core.contacts.imports.schemas import (
    ImportDryRunOut,
    ImportUploadOut,
    RowError,
)
from src.app.core.contacts.models import Contact
from src.app.shared.storage import get_storage


# Hard caps — `(a) 5 MB / 10K rows` per Step 3.5.10's recommendation.
# Predictable memory profile for inline processing; future Celery
# pathway lifts these.
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
MAX_ROW_COUNT = 10_000


# --- helpers --------------------------------------------------------------


def _normalise_phone(raw: str) -> str:
    """Strip non-digits + leading zeros. Empty → empty. The dedupe
    check uses this to compare existing contacts."""
    digits = "".join(c for c in (raw or "") if c.isdigit())
    return digits.lstrip("0") if digits else ""


async def _get_import(
    session: AsyncSession, import_id: uuid.UUID
) -> ContactImport:
    row = (
        await session.execute(
            select(ContactImport).where(ContactImport.id == import_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="contact import not found",
        )
    return row


# --- upload ---------------------------------------------------------------


async def upload_file(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    filename: str,
    file_bytes: bytes,
) -> ImportUploadOut:
    """Persist the file to local storage + parse just enough to render
    the mapping step UI. Returns the import row's id + suggested mapping
    + first 5 sample rows.

    Raises 413 if the file exceeds the size or row caps."""
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB cap.",
        )

    try:
        headers, sample, total = parse_headers_and_sample(
            file_bytes, filename
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    if total > MAX_ROW_COUNT:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File has {total} data rows; the cap is {MAX_ROW_COUNT}. "
                "Split the file and import in batches."
            ),
        )

    storage = get_storage()
    # Local-storage path: `imports/{org_id}/{uuid}.{ext}`. Keeps
    # forensic-trail files segregated per tenant.
    import_id = uuid.uuid4()
    ext = filename.rsplit(".", 1)[-1].lower()
    storage_path = f"imports/{org_id}/{import_id}.{ext}"
    storage.put(
        storage_path,
        file_bytes,
        content_type=(
            "text/csv"
            if ext == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )

    mapping = suggest_mapping(headers)

    row = ContactImport(
        id=import_id,
        org_id=org_id,
        filename=filename,
        storage_path=storage_path,
        uploaded_by_id=user_id,
        row_count=total,
        headers=headers,
        suggested_mapping=mapping,
        status=ContactImportStatus.uploaded,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    await audit.log(
        "contacts.import.uploaded",
        entity_type="contact_import",
        entity_id=row.id,
        after={"filename": filename, "row_count": total},
    )

    return ImportUploadOut(
        id=row.id,
        filename=row.filename,
        row_count=row.row_count,
        headers=list(row.headers),
        suggested_mapping=dict(row.suggested_mapping),
        sample_rows=sample,
    )


# --- dry-run --------------------------------------------------------------


async def dry_run_import(
    session: AsyncSession,
    *,
    import_id: uuid.UUID,
    mapping: dict[str, str],
) -> ImportDryRunOut:
    """Walk the file without writing. Reports per-row errors + dupe
    counts so the operator can decide whether to commit.

    Same parse pass the commit step uses — keeps the contract honest."""
    row = await _get_import(session, import_id)
    storage = get_storage()
    file_bytes = _read_file_bytes(storage, row.storage_path)

    existing_phones = await _load_existing_phone_set(session)

    will_insert = 0
    will_skip = 0
    duplicate_phone = 0
    errors: list[RowError] = []
    seen_phones_in_file: set[str] = set()

    for row_no, raw in parse_all_rows(file_bytes, row.filename):
        mapped = _apply_mapping(raw, mapping)

        if not mapped.get("full_name"):
            errors.append(
                RowError(row=row_no, reason="missing required field 'full_name'")
            )
            will_skip += 1
            continue

        phone_norm = _normalise_phone(mapped.get("phone") or "")
        if phone_norm and phone_norm in existing_phones:
            duplicate_phone += 1
            continue
        if phone_norm and phone_norm in seen_phones_in_file:
            duplicate_phone += 1
            continue
        if phone_norm:
            seen_phones_in_file.add(phone_norm)
        will_insert += 1

    # Persist the dry-run snapshot — operator's commit click should
    # match exactly what we just previewed (or rerun if the file
    # changed).
    row.applied_mapping = dict(mapping)
    row.status = ContactImportStatus.dry_run
    row.error_count = len(errors)
    row.error_log = [e.model_dump() for e in errors]
    await session.commit()

    return ImportDryRunOut(
        will_insert=will_insert,
        will_skip=will_skip,
        duplicate_phone=duplicate_phone,
        errors=errors,
    )


# --- commit ---------------------------------------------------------------


async def commit_import(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    import_id: uuid.UUID,
    mapping: dict[str, str],
    create_group: bool = False,
    group_name: Optional[str] = None,
) -> ContactImport:
    """Insert rows. Same parse + dedupe logic as dry-run; same errors
    surface in the persisted `error_log`. Optionally bundles the
    successfully-inserted contacts into a new static contact group."""
    row = await _get_import(session, import_id)
    storage = get_storage()
    file_bytes = _read_file_bytes(storage, row.storage_path)

    existing_phones = await _load_existing_phone_set(session)
    seen_phones_in_file: set[str] = set()
    inserted_ids: list[uuid.UUID] = []
    errors: list[dict[str, Any]] = []

    for row_no, raw in parse_all_rows(file_bytes, row.filename):
        mapped = _apply_mapping(raw, mapping)
        full_name = mapped.get("full_name")
        if not full_name:
            errors.append(
                {"row": row_no, "reason": "missing required field 'full_name'"}
            )
            continue

        phone_norm = _normalise_phone(mapped.get("phone") or "")
        if phone_norm and (
            phone_norm in existing_phones or phone_norm in seen_phones_in_file
        ):
            errors.append(
                {"row": row_no, "reason": f"duplicate phone {phone_norm}"}
            )
            continue

        contact_id = uuid.uuid4()
        tags = (
            [mapped["tag"].strip()]
            if mapped.get("tag") and mapped["tag"].strip()
            else []
        )
        contact = Contact(
            id=contact_id,
            org_id=org_id,
            full_name=full_name,
            phone=mapped.get("phone") or None,
            email=mapped.get("email") or None,
            source=mapped.get("source") or None,
            tags=tags,
        )
        session.add(contact)
        inserted_ids.append(contact_id)
        if phone_norm:
            seen_phones_in_file.add(phone_norm)

    # Flush contacts before the optional group + membership inserts
    # so the FK in `contact_group_members` resolves.
    await session.flush()

    created_group_id: Optional[uuid.UUID] = None
    if create_group and inserted_ids:
        if not group_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="`group_name` is required when `create_group=true`.",
            )
        group = ContactGroup(
            id=uuid.uuid4(),
            org_id=org_id,
            name=group_name,
            description=f"From import: {row.filename}",
            is_dynamic=False,
            filter_json=None,
            created_by_id=user_id,
        )
        session.add(group)
        await session.flush()
        created_group_id = group.id
        await session.execute(
            pg_insert(ContactGroupMember)
            .values(
                [
                    {
                        "org_id": org_id,
                        "group_id": group.id,
                        "contact_id": cid,
                    }
                    for cid in inserted_ids
                ]
            )
            .on_conflict_do_nothing(
                index_elements=["group_id", "contact_id"]
            )
        )

    row.applied_mapping = dict(mapping)
    row.success_count = len(inserted_ids)
    row.error_count = len(errors)
    row.error_log = errors
    row.created_group_id = created_group_id
    row.status = ContactImportStatus.committed
    await session.commit()
    await session.refresh(row)

    await audit.log(
        "contacts.import.committed",
        entity_type="contact_import",
        entity_id=row.id,
        after={
            "success_count": row.success_count,
            "error_count": row.error_count,
            "group_id": str(created_group_id) if created_group_id else None,
        },
    )
    return row


# --- internals ------------------------------------------------------------


def _read_file_bytes(storage, storage_path: str) -> bytes:
    """Read the uploaded file back from local storage. Wrapped so a
    future S3 backend swaps cleanly."""
    from pathlib import Path

    full = Path("./storage").resolve() / storage_path.lstrip("/")
    return full.read_bytes()


def _apply_mapping(
    raw: dict[str, str], mapping: dict[str, str]
) -> dict[str, str]:
    """Translate `{column: cell}` into `{contact_field: cell}` using
    the operator's mapping. Columns mapped to `'skip'` (or absent
    from the mapping) are dropped."""
    out: dict[str, str] = {}
    for column, value in raw.items():
        target = mapping.get(column, "skip")
        if target == "skip" or not target:
            continue
        out[target] = value
    return out


async def _load_existing_phone_set(session: AsyncSession) -> set[str]:
    """All existing phone numbers for the active tenant, normalised
    the same way `_normalise_phone` does. Used by dry-run + commit
    for dedupe detection without N+1 queries."""
    rows = (
        await session.execute(
            select(Contact.phone).where(Contact.phone.is_not(None))
        )
    ).scalars().all()
    return {_normalise_phone(p) for p in rows if p}


__all__ = [
    "MAX_FILE_SIZE_BYTES",
    "MAX_ROW_COUNT",
    "commit_import",
    "dry_run_import",
    "upload_file",
]
