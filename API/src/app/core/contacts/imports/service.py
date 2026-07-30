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
from src.app.core.custom_fields.data_access import list_fields_query
from src.app.core.custom_fields.models import CustomFieldDefinition
from src.app.shared import import_errors, validators
from src.app.shared.custom_fields.coercion import coerce_value
from src.app.shared.storage import get_storage

_CONTACT_ENTITY = "contact"
_CUSTOM_TARGET_PREFIX = "custom_data."

# Hard caps — 10 MB / 50K rows, matching the leads-import surface's
# ``_MAX_BYTES`` / ``_MAX_ROWS`` (see ``leads/imports/service.py``).
# Aligned 2026-07-30 so operators moving between the two wizards see
# identical size guidance. Inline processing means memory scales with
# row count, but 50K rows × ~1KB/row is still well under 100MB —
# safe for the current sync pathway.
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
MAX_ROW_COUNT = 50_000

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


# --- single-row read (used for polling) -----------------------------------


async def get_import(session: AsyncSession, import_id: uuid.UUID) -> ContactImport:
    """Public single-row fetch. Powers ``GET /contacts/imports/{id}``
    which the wizard polls after commit to watch the ``processing →
    committed`` transition."""
    return await _get_import(session, import_id)


# --- cancel ---------------------------------------------------------------


async def cancel_import(
    session: AsyncSession,
    *,
    import_id: uuid.UUID,
) -> ContactImport:
    """Operator-triggered abort. Allowed only on pre-terminal states
    (``uploaded`` / ``dry_run`` / ``processing``); a completed or
    already-cancelled row raises 409. Terminal transition is a simple
    status flip — the worker checks status on entry so a running job
    exits early on its next batch instead of being force-killed."""
    row = await _get_import(session, import_id)
    if row.status not in (
        ContactImportStatus.uploaded,
        ContactImportStatus.dry_run,
        ContactImportStatus.processing,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot cancel: import is in '{row.status.value}'. "
                "Cancel only works while uploaded, in dry-run, or processing."
            ),
        )
    row.status = ContactImportStatus.cancelled
    await session.commit()
    await session.refresh(row)

    await audit.log(
        "contacts.import.cancelled",
        entity_type="contact_import",
        entity_id=row.id,
        after={"prior_status": row.status.value},
    )
    return row


# --- history page ---------------------------------------------------------


async def list_imports(
    session: AsyncSession,
    *,
    status_filter: ContactImportStatus | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[ContactImport], int]:
    """Paginated list of contact-import rows for the caller's org.

    Powers the wizard's history page (parity with the leads-import
    history at ``GET /leads/import``). Tenant scope flows through the
    ORM filter on :class:`ContactImport`, so callers from foreign orgs
    see an empty list rather than a leak.
    """
    total = await data_access.count_imports_filtered(session, status_filter=status_filter)
    rows = await data_access.list_imports_page(
        session,
        status_filter=status_filter,
        offset=(page - 1) * size,
        limit=size,
    )
    return rows, total


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
    custom_defs = await _load_contact_custom_field_defs(session)
    _validate_mapping(mapping, custom_keys=set(custom_defs))
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
    errors: list[RowError] = []
    duplicates: list[RowError] = []
    warnings: list[RowError] = []
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

        # Reachability rule: a contact with no phone AND no email is
        # unreachable — reject as a hard error so the operator fixes
        # the source file rather than importing dead weight.
        method_error = _check_contact_method(row_no, mapped)
        if method_error is not None:
            errors.append(method_error)
            will_skip += 1
            continue

        # Custom-data coercion (typed cells against custom field defs).
        # Failures block the row so the operator fixes the value in the
        # source spreadsheet before commit — same treatment as a bad
        # standard-field shape.
        raw_custom = mapped.get("custom_data") or {}
        if raw_custom:
            _, cf_error = _coerce_custom_data_row(row_no, raw_custom, custom_defs)
            if cf_error is not None:
                errors.append(cf_error)
                will_skip += 1
                continue

        phone_norm = _normalise_phone(mapped.get("phone") or "")
        if phone_norm and (phone_norm in existing_phones or phone_norm in seen_phones_in_file):
            duplicates.append(
                RowError(
                    row=row_no,
                    column="phone",
                    value=mapped.get("phone"),
                    reason=f"duplicate phone {phone_norm}",
                )
            )
            continue
        if phone_norm:
            seen_phones_in_file.add(phone_norm)

        # Warnings never skip — the row would insert, we're just
        # flagging the value the importer had to coerce.
        for w in _collect_row_warnings(row_no, mapped):
            warnings.append(RowError(**w))
        will_insert += 1

    # Persist the dry-run snapshot — operator's commit click should
    # match exactly what we just previewed (or rerun if the file
    # changed). Stash `opt_in_source` here too so the commit step
    # doesn't need the wizard to send it again.
    row.applied_mapping = dict(mapping)
    row.status = ContactImportStatus.dry_run
    row.error_count = len(errors)
    row.error_log = [e.model_dump() for e in errors[:MAX_STORED_ERRORS]]
    row.duplicate_count = len(duplicates)
    row.duplicate_log = [d.model_dump() for d in duplicates[:MAX_STORED_ERRORS]]
    row.warning_count = len(warnings)
    row.warning_log = [w.model_dump() for w in warnings[:MAX_STORED_ERRORS]]
    if opt_in_source is not None:
        row.opt_in_source = opt_in_source
    await session.commit()

    return ImportDryRunOut(
        will_insert=will_insert,
        will_skip=will_skip,
        duplicate_phone=len(duplicates),
        duplicate_count=len(duplicates),
        warning_count=len(warnings),
        errors=errors,
        duplicates=duplicates,
        warnings=warnings,
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
    """Validate the request, persist the operator's intent, and hand
    the row loop off to Celery.

    Two-phase (2026-07-30 async pivot):

    1. **Validate + reserve** (this function, called under the request
       session): custom-field defs load, mapping validated, effective
       opt-in source folded onto the row, status flipped to
       ``processing``. Response returns immediately with the reserved
       row so the frontend can start polling.

    2. **Row loop** (``_run_commit`` below, invoked by the Celery
       worker in ``tasks.py``): parse + insert + persist counts,
       transition to ``committed`` / ``failed``.

    Idempotency: a re-hit while the row is already ``committed`` or
    ``processing`` returns the current state without re-dispatching —
    guards a rage-click on a slow response and a Celery retry that
    lands during the request window. ``cancelled`` rows raise 409
    so the operator sees why nothing happened.
    """
    row = await _get_import(session, import_id)

    if row.status == ContactImportStatus.committed:
        return row
    if row.status == ContactImportStatus.processing:
        return row  # already dispatched — worker will finalise
    if row.status == ContactImportStatus.cancelled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This import was cancelled. Re-upload the file to import again.",
        )

    custom_defs = await _load_contact_custom_field_defs(session)
    _validate_mapping(mapping, custom_keys=set(custom_defs))

    # Persist the operator's intent so the worker can rehydrate without
    # extra dispatch args.
    row.applied_mapping = dict(mapping)
    effective_opt_in_source = opt_in_source or row.opt_in_source
    if effective_opt_in_source:
        row.opt_in_source = effective_opt_in_source
    row.status = ContactImportStatus.processing
    await session.commit()
    await session.refresh(row)

    # Dispatch — Celery in prod, inline await in dev (no broker).
    # Local import breaks a circular dependency (tasks imports
    # ``_run_commit`` from this module).
    from src.app.core.contacts.imports.tasks import (
        HAS_CELERY,
        process_contact_import,
        process_contact_import_async,
    )

    if HAS_CELERY:
        process_contact_import.delay(
            str(row.id), str(org_id), str(user_id), create_group, group_name
        )
    else:
        await process_contact_import_async(
            row.id, org_id, user_id, create_group, group_name
        )
        await session.refresh(row)

    return row


async def _run_commit(
    session: AsyncSession,
    *,
    import_id: uuid.UUID,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    create_group: bool,
    group_name: str | None,
) -> ContactImport:
    """Worker body — reads the row's persisted ``applied_mapping`` +
    ``opt_in_source``, executes the row loop, and transitions to
    ``committed``. Called by both the async Celery task and the
    sync/dev fallback in :func:`commit_import`.

    Preconditions:
      - ``row.status == processing`` (set by ``commit_import``)
      - ``row.applied_mapping`` populated (ditto)

    Skips silently if the operator flipped the row to ``cancelled``
    while the worker was queued.
    """
    row = await _get_import(session, import_id)
    if row.status == ContactImportStatus.cancelled:
        return row
    if row.status != ContactImportStatus.processing:
        # Row already terminal (committed / failed) — no-op.
        return row

    mapping = dict(row.applied_mapping or {})
    effective_opt_in_source = row.opt_in_source
    custom_defs = await _load_contact_custom_field_defs(session)

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
    duplicates: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
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

        method_error = _check_contact_method(row_no, mapped)
        if method_error is not None:
            errors.append(method_error.model_dump())
            continue

        # Coerce mapped custom_data.<key> values against the org's
        # contact custom-field defs. A per-value failure (e.g. non-
        # numeric cell against a numeric field) blocks the row so the
        # source spreadsheet gets corrected before commit.
        cleaned_custom: dict[str, Any] = {}
        raw_custom = mapped.get("custom_data") or {}
        if raw_custom:
            cleaned_custom, cf_error = _coerce_custom_data_row(
                row_no, raw_custom, custom_defs
            )
            if cf_error is not None:
                errors.append(cf_error.model_dump())
                continue

        phone_norm = _normalise_phone(mapped.get("phone") or "")
        if phone_norm and (phone_norm in existing_phones or phone_norm in seen_phones_in_file):
            # 3-CSV split (2026-07-30): duplicates are a soft skip, not
            # a hard error. Operator downloads skipped.csv to see them.
            duplicates.append(
                {
                    "row": row_no,
                    "column": "phone",
                    "value": mapped.get("phone"),
                    "reason": f"duplicate phone {phone_norm}",
                }
            )
            continue

        # Row-level warnings (currently just tag truncation). Same
        # helper the dry-run uses so preview and commit stay in sync.
        warnings.extend(_collect_row_warnings(row_no, mapped))

        contact_id = uuid.uuid4()
        tag_value = mapped.get("tag")
        # Normalise, dedupe, trim, and cap. `Contact.tags` is
        # `ARRAY(String(64))` — an unbounded tag from a CSV cell
        # otherwise raises `DataError` mid-batch and rolls back every
        # already-inserted row up to that point. Warning emission for
        # the truncation lives in `_collect_row_warnings` above.
        raw_tags: list[str] = (
            tag_value
            if isinstance(tag_value, list)
            else ([tag_value] if isinstance(tag_value, str) else [])
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
            custom_data=cleaned_custom,
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
    row.duplicate_count = len(duplicates)
    row.duplicate_log = duplicates[:MAX_STORED_ERRORS]
    row.warning_count = len(warnings)
    row.warning_log = warnings[:MAX_STORED_ERRORS]
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
            "duplicate_count": row.duplicate_count,
            "warning_count": row.warning_count,
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


def _check_contact_method(row_no: int, mapped: dict[str, Any]) -> RowError | None:
    """Reject rows that carry neither a phone nor an email.

    Every contact needs at least one channel to be reachable from the
    CRM — without one, the row is useless clutter (no way to call, no
    way to email, no way to WhatsApp). Enforced 2026-07-30 after
    operator feedback that blank-phone-blank-email imports were slipping
    through. ``full_name``-only prospect lists must supply at least one
    channel; empty rows should be filtered from the source spreadsheet
    before upload.
    """
    phone_raw = (mapped.get("phone") or "").strip()
    email_raw = (mapped.get("email") or "").strip()
    if not phone_raw and not email_raw:
        return RowError(
            row=row_no,
            column="phone",
            value=None,
            reason="row has neither phone nor email — at least one contact method is required",
        )
    return None


def _collect_row_warnings(row_no: int, mapped: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the per-row warnings (import succeeds but a value was
    coerced). Shared between dry-run and commit so the preview reflects
    exactly what the commit CSV will contain.

    Today the only warning is **tag truncation** — ``Contact.tags`` is
    ``ARRAY(String(64))`` and anything longer gets cut to 64 chars.
    Add new warning kinds here rather than in the commit loop so the
    dry-run preview never drifts.
    """
    tag_value = mapped.get("tag")
    raw_tags: list[str] = (
        tag_value
        if isinstance(tag_value, list)
        else ([tag_value] if isinstance(tag_value, str) else [])
    )
    out: list[dict[str, Any]] = []
    for t in raw_tags:
        original = str(t).strip()
        if original and len(original) > 64:
            cleaned = original[:64]
            out.append(
                {
                    "row": row_no,
                    "column": "tag",
                    "value": original,
                    "reason": (
                        f"tag truncated to 64 chars (was {len(original)}); "
                        f"kept {cleaned!r}"
                    ),
                }
            )
    return out


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


_STANDARD_TARGETS: frozenset[str] = frozenset(
    {"full_name", "phone", "email", "source", "tag"}
)


async def _load_contact_custom_field_defs(
    session: AsyncSession,
) -> dict[str, CustomFieldDefinition]:
    """Load the org's contact custom-field defs once, keyed by
    ``field_key``. Hidden fields are excluded to match the FE loader.

    Callers use this both to gate `_validate_mapping` (via the key set)
    and to coerce per-row values (via the full defs). Loading once per
    import instead of once per row keeps the loop O(N) instead of
    O(N × k) round-trips.
    """
    fields = await list_fields_query(
        session, entity_type=_CONTACT_ENTITY, include_hidden=False
    )
    return {f.field_key: f for f in fields}


def _coerce_custom_data_row(
    row_no: int,
    custom_data: dict[str, Any],
    defs: dict[str, CustomFieldDefinition],
) -> tuple[dict[str, Any], RowError | None]:
    """Coerce a single row's custom-data dict against the pre-loaded
    field defs. Returns ``(cleaned, error)``; ``error`` is populated
    when any single value fails type coercion (e.g. non-numeric cell
    against a numeric field). Stops at the first failing key so the
    operator fixes them one at a time — matches ``_check_row_shape``.

    Uses ``coerce_value`` inline rather than ``validate_custom_data``
    to avoid a DB round-trip per row.
    """
    cleaned: dict[str, Any] = {}
    for key, value in custom_data.items():
        defn = defs.get(key)
        if defn is None:  # pragma: no cover - mapping validator rejects unknowns
            return cleaned, RowError(
                row=row_no,
                column=f"custom_data.{key}",
                value=str(value) if value is not None else None,
                reason=f"custom field {key!r} is not defined for entity 'contact'",
            )
        try:
            cleaned[key] = coerce_value(defn.field_type, key, value)
        except HTTPException as exc:
            return cleaned, RowError(
                row=row_no,
                column=f"custom_data.{key}",
                value=str(value) if value is not None else None,
                reason=str(exc.detail),
            )
    return cleaned, None


def _validate_mapping(mapping: dict[str, str], *, custom_keys: set[str]) -> None:
    """Reject mappings the import loop cannot honour.

    Three shapes get a 422 at dry-run/commit entry, before any row work:

    1. **Required target unmapped.** ``full_name`` must appear as a
       target on some column — without it every row fails the required
       check and the import wastes a full parse pass. The frontend
       gates this via ``canRunDryRun``; the backend re-enforces so a
       direct API caller (or a stale FE build) can't sneak in an
       empty-outcome import.

    2. **Unknown targets.** A target must be either ``"skip"``, one of
       the standard fields (``full_name`` / ``phone`` / ``email`` /
       ``source`` / ``tag``), or ``custom_data.<key>`` where ``<key>``
       is a defined custom field for entity ``contact`` in this tenant.
       Junk targets from a stale FE build get rejected with the exact
       list so the operator sees which columns need re-mapping.

    3. **Duplicate non-tag targets.** Silent last-write-wins on
       ``full_name`` / ``phone`` / ``email`` / ``source`` / any
       ``custom_data.<key>`` corrupts data — surface the conflict so
       the operator picks one column and marks the other ``skip``.
       Duplicate ``tag`` targets are allowed (they aggregate via
       ``_apply_mapping``).
    """
    non_tag_seen: dict[str, str] = {}
    conflicts: list[str] = []
    targets_seen: set[str] = set()
    unknown: list[str] = []
    for column, target in mapping.items():
        if not target or target == "skip":
            continue
        # Bucket the target by shape so we can validate it.
        if target in _STANDARD_TARGETS:
            pass
        elif target.startswith(_CUSTOM_TARGET_PREFIX):
            key = target[len(_CUSTOM_TARGET_PREFIX) :]
            if not key or key not in custom_keys:
                unknown.append(target)
                continue
        else:
            unknown.append(target)
            continue

        targets_seen.add(target)
        if target == "tag":
            continue
        prior = non_tag_seen.get(target)
        if prior is not None:
            conflicts.append(f"{prior!r} and {column!r} both map to {target!r}")
        else:
            non_tag_seen[target] = column
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Mapping references unknown targets: "
                f"{sorted(set(unknown))}. Allowed standard targets: "
                f"{sorted(_STANDARD_TARGETS)}; custom-field targets must be of "
                "the form 'custom_data.<key>' where <key> is a defined custom "
                "field for entity 'contact'."
            ),
        )
    if "full_name" not in targets_seen:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Map one column to 'Full name' — it's required for every contact.",
        )
    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Duplicate mapping targets: " + "; ".join(conflicts),
        )


def _apply_mapping(raw: dict[str, str], mapping: dict[str, str]) -> dict[str, Any]:
    """Translate `{column: cell}` into `{contact_field: cell(s)}` using
    the operator's mapping. Columns mapped to `'skip'` (or absent from
    the mapping) are dropped.

    Special-cases:

    - ``target='tag'`` — values are aggregated into a list so two CSV
      columns both mapped to ``tag`` (or a single column carrying
      comma-separated tags like ``"vip, priority, hot"``) merge into
      the contact's ``tags`` array instead of last-write-wins.

    - ``target='custom_data.<key>'`` — values collect into a
      ``custom_data`` dict on the returned mapping. Blank cells are
      dropped so the downstream ``validate_custom_data`` doesn't
      complain about empty strings against typed fields (numeric,
      date, …). ``<key>`` is trusted to be a valid contact custom
      field — ``_validate_mapping`` rejected the mapping upstream if
      it wasn't.
    """
    out: dict[str, Any] = {}
    tags_bucket: list[str] = []
    custom_bucket: dict[str, Any] = {}
    for column, value in raw.items():
        target = mapping.get(column, "skip")
        if target == "skip" or not target:
            continue
        if target == "tag":
            for chunk in _split_tag_cell(value):
                if chunk and chunk not in tags_bucket:
                    tags_bucket.append(chunk)
            continue
        if target.startswith(_CUSTOM_TARGET_PREFIX):
            key = target[len(_CUSTOM_TARGET_PREFIX) :]
            if key and value not in (None, ""):
                custom_bucket[key] = value
            continue
        out[target] = value
    if tags_bucket:
        out["tag"] = tags_bucket
    if custom_bucket:
        out["custom_data"] = custom_bucket
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


# --- CSV download helpers -------------------------------------------------


async def _build_report_csv_response(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    import_id: uuid.UUID,
    kind: str,
) -> StreamingResponse:
    """Shared body for the three per-import report downloads.

    ``kind`` is one of ``"errors"`` / ``"skipped"`` / ``"warnings"`` and
    selects which persisted JSONB log to render. All three share the
    ``shared.import_errors.write_errors_csv`` output shape — original
    columns + ``__row_number`` / ``__column`` / ``__value`` /
    ``__error_reason`` — so a downstream tool that parses one file
    parses all three.
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

    if kind == "errors":
        persisted = row.error_log or []
    elif kind == "skipped":
        persisted = row.duplicate_log or []
    elif kind == "warnings":
        persisted = row.warning_log or []
    else:  # pragma: no cover - internal-only guard
        raise ValueError(f"unknown report kind: {kind!r}")

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

    records_out: list[import_errors.ImportRowError] = []
    for record in persisted:
        records_out.append(
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
        errors=records_out,
    )

    filename = f"contact-import-{import_id}-{kind}.csv"
    return StreamingResponse(
        iter([body]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def build_errors_csv_response(
    session: AsyncSession, *, org_id: uuid.UUID, import_id: uuid.UUID
) -> StreamingResponse:
    """Stream the errors CSV (hard failures — required missing, invalid
    shape). Content is derived from the persisted ``error_log`` so the
    operator gets exactly what they were shown in the wizard preview."""
    return await _build_report_csv_response(
        session, org_id=org_id, import_id=import_id, kind="errors"
    )


async def build_skipped_csv_response(
    session: AsyncSession, *, org_id: uuid.UUID, import_id: uuid.UUID
) -> StreamingResponse:
    """Stream the skipped-duplicates CSV (rows whose phone collapsed
    onto an existing contact or an earlier row in the same file).
    Mirrors ``GET /leads/imports/{id}/skipped.csv``."""
    return await _build_report_csv_response(
        session, org_id=org_id, import_id=import_id, kind="skipped"
    )


async def build_warnings_csv_response(
    session: AsyncSession, *, org_id: uuid.UUID, import_id: uuid.UUID
) -> StreamingResponse:
    """Stream the warnings CSV (rows that imported but had a value
    coerced — e.g. tag truncation). Mirrors
    ``GET /leads/imports/{id}/warnings.csv``."""
    return await _build_report_csv_response(
        session, org_id=org_id, import_id=import_id, kind="warnings"
    )


__all__ = [
    "MAX_FILE_SIZE_BYTES",
    "MAX_ROW_COUNT",
    "MAX_STORED_ERRORS",
    "build_errors_csv_response",
    "build_skipped_csv_response",
    "build_warnings_csv_response",
    "cancel_import",
    "commit_import",
    "dry_run_import",
    "get_import",
    "list_imports",
    "upload_file",
]
