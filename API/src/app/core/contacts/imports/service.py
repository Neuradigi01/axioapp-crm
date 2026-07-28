"""Service layer for contact bulk imports — upload, dry-run, commit."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.contacts.groups.models import ContactGroup
from src.app.core.contacts.imports import data_access
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
from src.app.shared import import_errors, validators
from src.app.shared.storage import get_storage

# Hard caps — `(a) 5 MB / 10K rows` per Step 3.5.10's recommendation.
# Predictable memory profile for inline processing; future Celery
# pathway lifts these.
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
MAX_ROW_COUNT = 10_000

# Cap persisted error records so an import with 10K rows that all fail
# does not bloat the `error_log` JSONB into a multi-MB blob. The CSV
# response still streams the full pass; only the DB-stored snapshot
# is truncated.
MAX_STORED_ERRORS = 5_000


# --- helpers --------------------------------------------------------------


def _normalise_phone(raw: str) -> str:
    """Strip non-digits and return the last 10 digits.

    Mirrors ``contacts.service._normalise_phone_suffix`` so a phone
    number entered via the CRM's create modal (``+91 9000000001``,
    stored raw) and the same number arriving in a CSV row
    (``9000000001``) collapse onto the same dedupe key. Previously
    this stripped leading zeros only, so the CRM's raw ``+91`` prefix
    made every CRM-created contact look distinct from its bulk-import
    twin. Short (<6-digit) inputs return "" — same guard as the CRM
    side so a rogue single-digit doesn't drop us to a mega-collision
    key.
    """
    digits = "".join(c for c in (raw or "") if c.isdigit())
    if len(digits) < 6:
        return ""
    return digits[-10:] if len(digits) >= 10 else digits


async def _get_import(session: AsyncSession, import_id: uuid.UUID) -> ContactImport:
    row = await data_access.get_import_by_id(session, import_id)
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
        headers, sample, total = parse_headers_and_sample(file_bytes, filename)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

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

    row = data_access.add_import(
        session,
        ContactImport(
            id=import_id,
            org_id=org_id,
            filename=filename,
            storage_path=storage_path,
            uploaded_by_id=user_id,
            row_count=total,
            headers=headers,
            suggested_mapping=mapping,
            status=ContactImportStatus.uploaded,
        ),
    )
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
    opt_in_source: str | None = None,
) -> ImportDryRunOut:
    """Walk the file without writing. Reports per-row errors + dupe
    counts so the operator can decide whether to commit.

    Same parse pass the commit step uses — keeps the contract honest."""
    row = await _get_import(session, import_id)
    _validate_mapping(mapping)
    storage = get_storage()
    file_bytes = _read_file_bytes(storage, row.storage_path)

    # Pass 1 — gather candidate phone keys from the incoming file so the
    # existence check can target just those keys instead of streaming
    # every phone in the tenant.
    parsed_rows = list(parse_all_rows(file_bytes, row.filename))
    candidate_phones: set[str] = set()
    for _row_no, raw in parsed_rows:
        mapped = _apply_mapping(raw, mapping)
        phone_norm = _normalise_phone(mapped.get("phone") or "")
        if phone_norm:
            candidate_phones.add(phone_norm)
    existing_phones = await _dedupe_key_hits(session, candidates=candidate_phones)

    will_insert = 0
    will_skip = 0
    duplicate_phone = 0
    errors: list[RowError] = []
    seen_phones_in_file: set[str] = set()

    for row_no, raw in parsed_rows:
        mapped = _apply_mapping(raw, mapping)

        if not mapped.get("full_name"):
            errors.append(
                RowError(
                    row=row_no,
                    column="full_name",
                    value=None,
                    reason=validators.REASON_REQUIRED_MISSING,
                )
            )
            will_skip += 1
            continue

        # Field-shape validators (name / email / phone). Failures don't
        # write and don't count as inserts.
        shape_error = _check_row_shape(row_no, mapped)
        if shape_error is not None:
            errors.append(shape_error)
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
    # changed). Stash `opt_in_source` here too so the commit step
    # doesn't need the wizard to send it again.
    row.applied_mapping = dict(mapping)
    row.status = ContactImportStatus.dry_run
    row.error_count = len(errors)
    row.error_log = [e.model_dump() for e in errors[:MAX_STORED_ERRORS]]
    if opt_in_source is not None:
        row.opt_in_source = opt_in_source
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
    group_name: str | None = None,
    opt_in_source: str | None = None,
) -> ContactImport:
    """Insert rows. Same parse + dedupe logic as dry-run; same errors
    surface in the persisted `error_log`. Optionally bundles the
    successfully-inserted contacts into a new static contact group.

    Idempotent: once ``row.status`` is ``committed`` a re-invocation
    returns the existing row without touching contacts. Guards a
    network-stall rage-click from inserting the whole file a second
    time.
    """
    row = await _get_import(session, import_id)

    # Idempotency: refuse to re-commit an already-committed import row.
    # Prior behaviour was a silent re-insert of every contact — the
    # frontend comment claimed idempotency the backend didn't have.
    if row.status == ContactImportStatus.committed:
        return row

    _validate_mapping(mapping)

    # Fold the effective opt-in source: prefer the fresh caller value,
    # otherwise use what dry-run stashed on the row.
    effective_opt_in_source = opt_in_source or row.opt_in_source

    storage = get_storage()
    file_bytes = _read_file_bytes(storage, row.storage_path)

    # Pass 1 — collect candidate phone keys so the existence check
    # touches only the working set.
    parsed_rows = list(parse_all_rows(file_bytes, row.filename))
    candidate_phones: set[str] = set()
    for _row_no, raw in parsed_rows:
        mapped = _apply_mapping(raw, mapping)
        phone_norm = _normalise_phone(mapped.get("phone") or "")
        if phone_norm:
            candidate_phones.add(phone_norm)
    existing_phones = await _dedupe_key_hits(session, candidates=candidate_phones)

    seen_phones_in_file: set[str] = set()
    inserted_ids: list[uuid.UUID] = []
    errors: list[dict[str, Any]] = []
    opt_in_recorded_at = datetime.now(UTC) if effective_opt_in_source else None

    for row_no, raw in parsed_rows:
        mapped = _apply_mapping(raw, mapping)
        full_name = mapped.get("full_name")
        if not full_name:
            errors.append(
                {
                    "row": row_no,
                    "column": "full_name",
                    "value": None,
                    "reason": validators.REASON_REQUIRED_MISSING,
                }
            )
            continue

        shape_error = _check_row_shape(row_no, mapped)
        if shape_error is not None:
            errors.append(shape_error.model_dump())
            continue

        phone_norm = _normalise_phone(mapped.get("phone") or "")
        if phone_norm and (phone_norm in existing_phones or phone_norm in seen_phones_in_file):
            errors.append(
                {
                    "row": row_no,
                    "column": "phone",
                    "value": mapped.get("phone"),
                    "reason": f"duplicate phone {phone_norm}",
                }
            )
            continue

        contact_id = uuid.uuid4()
        tag_value = mapped.get("tag")
        # Normalise, dedupe, trim, and cap. `Contact.tags` is
        # `ARRAY(String(64))` — an unbounded tag from a CSV cell
        # otherwise raises `DataError` mid-batch and rolls back every
        # already-inserted row up to that point.
        raw_tags: list[str] = tag_value if isinstance(tag_value, list) else (
            [tag_value] if isinstance(tag_value, str) else []
        )
        tags: list[str] = []
        for t in raw_tags:
            cleaned = str(t).strip()[:64]
            if cleaned and cleaned not in tags:
                tags.append(cleaned)
        contact = Contact(
            id=contact_id,
            org_id=org_id,
            full_name=full_name,
            phone=mapped.get("phone") or None,
            email=mapped.get("email") or None,
            source=mapped.get("source") or None,
            tags=tags,
        )
        if effective_opt_in_source:
            # DPDP: stamp the operator-chosen provenance on each row.
            # Bulk imports never carry an explicit "yes" — the operator
            # asserts they have consent from an offline capture; that's
            # `opted_in` state. A future "unknown" branch could set
            # `implicit` for prospecting lists.
            contact.whatsapp_opt_in_status = "opted_in"
            contact.whatsapp_opt_in_source = effective_opt_in_source
            contact.whatsapp_opt_in_recorded_at = opt_in_recorded_at
            contact.whatsapp_opt_in_recorded_by_user_id = user_id
        data_access.add_contact(session, contact)
        inserted_ids.append(contact_id)
        if phone_norm:
            seen_phones_in_file.add(phone_norm)

    # Flush contacts before the optional group + membership inserts
    # so the FK in `contact_group_members` resolves.
    await session.flush()

    created_group_id: uuid.UUID | None = None
    if create_group and inserted_ids:
        if not group_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="`group_name` is required when `create_group=true`.",
            )
        group = data_access.add_group(
            session,
            ContactGroup(
                id=uuid.uuid4(),
                org_id=org_id,
                name=group_name,
                description=f"From import: {row.filename}",
                is_dynamic=False,
                filter_json=None,
                created_by_id=user_id,
            ),
        )
        await session.flush()
        created_group_id = group.id
        await data_access.bulk_upsert_group_members(
            session,
            org_id=org_id,
            group_id=group.id,
            contact_ids=inserted_ids,
        )

    row.applied_mapping = dict(mapping)
    row.success_count = len(inserted_ids)
    row.error_count = len(errors)
    row.error_log = errors[:MAX_STORED_ERRORS]
    row.created_group_id = created_group_id
    if effective_opt_in_source:
        row.opt_in_source = effective_opt_in_source
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


def _check_row_shape(row_no: int, mapped: dict[str, Any]) -> RowError | None:
    """Run the shared per-field validators against a mapped row.

    Returns the first failure as a `RowError`, or `None` if the row
    passes every shape check. Only fields that are *present* get
    validated (the required-field check runs separately upstream); an
    absent optional email or phone is allowed through.
    """
    full_name = mapped.get("full_name") or ""
    try:
        validators.validate_name(full_name)
    except validators.ValidationError as exc:
        return RowError(
            row=row_no,
            column="full_name",
            value=full_name,
            reason=exc.reason,
        )

    email_raw = (mapped.get("email") or "").strip()
    if email_raw:
        try:
            validators.validate_email(email_raw)
        except validators.ValidationError as exc:
            return RowError(
                row=row_no,
                column="email",
                value=email_raw,
                reason=exc.reason,
            )

    phone_raw = (mapped.get("phone") or "").strip()
    if phone_raw:
        try:
            validators.validate_phone(phone_raw)
        except validators.ValidationError as exc:
            return RowError(
                row=row_no,
                column="phone",
                value=phone_raw,
                reason=exc.reason,
            )

    return None


def _validate_mapping(mapping: dict[str, str]) -> None:
    """Reject a mapping where two columns land on the same non-tag
    target. Silent last-write-wins on `full_name` / `phone` / `email`
    / `source` corrupts data — surface the conflict as a 422 so the
    operator picks one column and marks the other `skip`.

    Duplicate `tag` targets are allowed (they aggregate via
    `_apply_mapping`).
    """
    non_tag_seen: dict[str, str] = {}
    conflicts: list[str] = []
    for column, target in mapping.items():
        if not target or target == "skip" or target == "tag":
            continue
        prior = non_tag_seen.get(target)
        if prior is not None:
            conflicts.append(f"{prior!r} and {column!r} both map to {target!r}")
        else:
            non_tag_seen[target] = column
    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Duplicate mapping targets: " + "; ".join(conflicts),
        )


def _apply_mapping(raw: dict[str, str], mapping: dict[str, str]) -> dict[str, Any]:
    """Translate `{column: cell}` into `{contact_field: cell(s)}` using
    the operator's mapping. Columns mapped to `'skip'` (or absent from
    the mapping) are dropped.

    Special-cases ``target='tag'``: the value is returned as a list so
    two CSV columns both mapped to ``tag`` (or a single column carrying
    comma-separated tags like ``"vip, priority, hot"``) aggregate
    into the contact's ``tags`` array instead of last-write-wins."""
    out: dict[str, Any] = {}
    tags_bucket: list[str] = []
    for column, value in raw.items():
        target = mapping.get(column, "skip")
        if target == "skip" or not target:
            continue
        if target == "tag":
            for chunk in _split_tag_cell(value):
                if chunk and chunk not in tags_bucket:
                    tags_bucket.append(chunk)
            continue
        out[target] = value
    if tags_bucket:
        out["tag"] = tags_bucket
    return out


def _split_tag_cell(cell: str) -> list[str]:
    """Break a tag CSV cell on ``,`` / ``;`` / ``|`` and trim each piece.
    Empty pieces are dropped. A cell without a separator returns one
    element."""
    if not cell:
        return []
    pieces: list[str] = []
    for chunk in cell.replace(";", ",").replace("|", ",").split(","):
        stripped = chunk.strip()
        if stripped:
            pieces.append(stripped)
    return pieces


async def _dedupe_key_hits(
    session: AsyncSession, *, candidates: set[str]
) -> set[str]:
    """Return the subset of normalised phone keys already present in
    the tenant's contacts table.

    Replaces the old ``_load_existing_phone_set`` which streamed EVERY
    phone for the tenant into memory on every dry-run and every commit
    (500K contacts ≈ 50MB per request). Now we only ask the DB about
    the keys that appear in *this* file — the working set is at most
    ``MAX_ROW_COUNT``.
    """
    if not candidates:
        return set()
    rows = await data_access.list_matching_phones_by_suffix(
        session, suffixes=list(candidates)
    )
    hits: set[str] = set()
    for raw in rows:
        if not raw:
            continue
        key = _normalise_phone(raw)
        if key in candidates:
            hits.add(key)
    return hits


# --- errors.csv download --------------------------------------------------


async def build_errors_csv_response(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    import_id: uuid.UUID,
) -> StreamingResponse:
    """Stream a CSV of every failed row for a completed import.

    Columns are the original file columns + `__row_number`, `__column`,
    `__value`, `__error_reason` — same shape the shared
    `shared.import_errors.write_errors_csv` helper produces for the
    other two import surfaces. Content is derived from the persisted
    `error_log` (dry-run or commit) so the operator gets exactly what
    they were shown in the wizard preview.
    """
    row = await _get_import(session, import_id)
    if row.org_id != org_id:
        # RLS already gates the query, but the explicit guard makes the
        # 404 shape identical whether the row is missing or belongs to
        # another tenant.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="contact import not found",
        )

    # Load the original file so the CSV echoes back the offending row
    # data verbatim — operators fix the source spreadsheet against the
    # column they see in the download.
    storage = get_storage()
    file_bytes = _read_file_bytes(storage, row.storage_path)
    parsed_rows = list(parse_all_rows(file_bytes, row.filename))
    headers: list[str] = list(row.headers or [])
    if not headers and parsed_rows:
        headers = list(parsed_rows[0][1].keys())

    original_rows: list[dict[str, Any]] = [raw for _row_no, raw in parsed_rows]

    persisted = row.error_log or []
    errors_out: list[import_errors.ImportRowError] = []
    for record in persisted:
        errors_out.append(
            import_errors.ImportRowError(
                row_number=int(record.get("row", 0)),
                column=record.get("column"),
                value=(
                    None
                    if record.get("value") is None
                    else str(record.get("value"))
                ),
                reason=str(record.get("reason", "")),
            )
        )

    body = import_errors.write_errors_csv(
        original_headers=headers,
        original_rows=original_rows,
        errors=errors_out,
    )

    filename = f"contact-import-{import_id}-errors.csv"
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = [
    "MAX_FILE_SIZE_BYTES",
    "MAX_ROW_COUNT",
    "MAX_STORED_ERRORS",
    "build_errors_csv_response",
    "commit_import",
    "dry_run_import",
    "upload_file",
]
