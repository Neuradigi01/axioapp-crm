"""Celery task that drives a bulk import end-to-end.

`process_lead_import(import_id)` is enqueued by the commit-mapping
endpoint (Step 2 of the bulk-import track). It:

  1. Loads the `LeadImport` row, transitions `awaiting_mapping →
     processing`. Skips work if the row is already in a terminal state
     (idempotent — Celery retries / re-replays land cleanly).
  2. Iterates the source file via `parser.parse_rows(...)`.
  3. For each data row:
       - dedup-checks against existing contacts in the org;
       - creates a contact + lead in a SAVEPOINT;
       - row failure → push to error list, continue with the next row.
  4. Writes a per-import `errors.csv` to the storage backend.
  5. Updates the row to `completed` with `counts`.
  6. Emits `lead_imports.completed` audit event.

Catastrophic failures (file unreadable, mapping invalid at parse time)
transition the import to `failed`; the exception bubbles up so Celery
records the failure too.

Bridging to async: Celery's executor is synchronous, so the task body
uses `asyncio.run(...)` to drive the async session + service work.
This is the same pattern `src/celery/tasks.py` already uses.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import uuid
from typing import Any, Optional

try:
    from celery import shared_task as _shared_task

    HAS_CELERY = True
except ImportError:  # pragma: no cover - celery not always installed in dev
    HAS_CELERY = False

    # Fallback shim so module imports work even when celery is absent.
    # The shim's `.delay()` is a no-op — call sites that need the
    # task to run synchronously (in dev) instead await
    # `process_lead_import_async(...)` directly. See `commit_mapping`
    # in service.py for the branching.
    def _shared_task(*decorator_args: Any, **decorator_kwargs: Any):
        def _wrap(fn):
            class _Stub:
                __name__ = fn.__name__
                __doc__ = fn.__doc__

                def __call__(self, *a, **kw):
                    return fn(*a, **kw)

                def delay(self, *a, **kw):
                    return None

                def apply(self, args=None, kwargs=None, **_):
                    return fn(*(args or ()), **(kwargs or {}))

            return _Stub()

        if decorator_args and callable(decorator_args[0]) and not decorator_kwargs:
            return _wrap(decorator_args[0])
        return _wrap

from sqlalchemy import select

from src.app.core import audit
from src.app.core.contacts.schemas import ContactCreate
from src.app.core.contacts.service import create_contact
from src.app.core.custom_fields.models import CustomFieldDefinition
from src.app.core.leads.imports.dedup import find_existing_contact
from src.app.core.leads.imports.models import LeadImport, LeadImportStatus
from src.app.core.leads.imports.parser import HeaderInfo, ParsedRow, parse_rows
from src.app.core.leads.ingest import ingest as ingest_lead
from src.app.core.leads.models import LeadSource
from src.app.core.leads.schemas import LeadCreate
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.db import async_session
from src.app.shared.storage import get_storage


logger = logging.getLogger(__name__)


_TERMINAL_STATUSES = {
    LeadImportStatus.completed,
    LeadImportStatus.failed,
    LeadImportStatus.cancelled,
}


@_shared_task(name="src.app.core.leads.imports.tasks.process_lead_import")
def process_lead_import(import_id: str) -> dict[str, Any]:
    """Celery entrypoint (sync). Bridges into the async body via
    `asyncio.run(...)` — Celery workers run with no event loop of their
    own. Call sites running inside an event loop (the dev fallback in
    `service.commit_mapping`) skip this entrypoint and await
    `process_lead_import_async(...)` directly.
    """
    return asyncio.run(process_lead_import_async(uuid.UUID(import_id)))


# --- internals --------------------------------------------------------


async def process_lead_import_async(import_id: uuid.UUID) -> dict[str, Any]:
    """Pre-flight: claim the row, set status `processing`, capture the
    fields we need for the rest of the run. Returns early with a no-op
    result if the row is gone or already terminal (idempotency)."""
    async with async_session() as session:
        row = (
            await session.execute(
                select(LeadImport).where(LeadImport.id == import_id)
            )
        ).scalar_one_or_none()
        if row is None:
            logger.warning("process_lead_import: %s not found", import_id)
            return {"status": "missing"}
        if row.status in _TERMINAL_STATUSES:
            logger.info(
                "process_lead_import: %s already %s — no-op",
                import_id, row.status.value,
            )
            return {"status": row.status.value, "counts": row.counts or {}}
        if row.status != LeadImportStatus.mapping_committed:
            # Either still awaiting_mapping (mapping not committed yet)
            # or already processing (another worker has it). No-op so we
            # don't double-process.
            logger.info(
                "process_lead_import: %s in %s — refusing to run",
                import_id, row.status.value,
            )
            return {"status": row.status.value}
        org_id = row.org_id
        uploader = row.uploaded_by
        storage_path = row.storage_path
        mapping = row.mapping or {}
        row.status = LeadImportStatus.processing
        await session.commit()

    # Set tenant context so RLS authorises the worker's queries +
    # `audit.log` derives the correct org/actor without explicit kwargs.
    token = set_context(RequestContext(org_id=org_id, user_id=uploader))
    try:
        try:
            header, rows_iter = parse_rows(storage_path, mapping)
        except Exception as exc:
            logger.exception("process_lead_import: parse failed for %s", import_id)
            await _mark_failed(import_id, str(exc))
            raise

        try:
            counts, error_rows = await _commit_rows(
                org_id=org_id, mapping=mapping, rows_iter=rows_iter
            )
        except Exception as exc:
            logger.exception("process_lead_import: commit failed for %s", import_id)
            await _mark_failed(import_id, str(exc))
            raise

        error_report_path: Optional[str] = None
        if error_rows:
            error_report_path = await _write_error_csv(
                org_id=org_id,
                import_id=import_id,
                header=header,
                error_rows=error_rows,
            )

        async with async_session() as session:
            row = (
                await session.execute(
                    select(LeadImport).where(LeadImport.id == import_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return {"status": "missing"}
            row.status = LeadImportStatus.completed
            row.counts = counts
            row.error_report_path = error_report_path
            await session.commit()

        await audit.log(
            "lead_imports.completed",
            entity_type="lead_import",
            entity_id=import_id,
            after={
                "import_id": str(import_id),
                "counts": counts,
                "error_report_path": error_report_path,
            },
        )
        return {"status": "completed", "counts": counts}
    finally:
        reset_context(token)


async def _load_custom_field_routing(
    org_id: uuid.UUID,
) -> tuple[set[str], set[str]]:
    """Return (contact_cf_keys, lead_cf_keys) — the field_keys defined
    for each entity in this org's `custom_field_definitions`.

    Used to route mapped `custom_data.<key>` values into the right
    entity's `custom_data` dict at row-commit time. Same field_key on
    both entities is allowed — the value lands in both.
    """
    contact_keys: set[str] = set()
    lead_keys: set[str] = set()
    async with async_session() as session:
        rows = (
            await session.execute(
                select(
                    CustomFieldDefinition.field_key,
                    CustomFieldDefinition.entity_type,
                ).where(
                    CustomFieldDefinition.entity_type.in_(("contact", "lead"))
                )
            )
        ).all()
    for field_key, entity in rows:
        if entity == "contact":
            contact_keys.add(field_key)
        elif entity == "lead":
            lead_keys.add(field_key)
    return contact_keys, lead_keys


def _split_custom_data(
    mapped: dict[str, Optional[str]],
    contact_keys: set[str],
    lead_keys: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pull `custom_data.<key>` entries out of the per-row mapped dict
    and bucket them into contact_custom / lead_custom based on which
    entity each field is defined for. Empty / null values are skipped
    so we don't fight `_validate_custom_data` over None for
    optional fields."""
    contact_custom: dict[str, Any] = {}
    lead_custom: dict[str, Any] = {}
    for crm_key, value in mapped.items():
        if not crm_key.startswith("custom_data."):
            continue
        if value is None or value == "":
            continue
        cf_key = crm_key[len("custom_data.") :]
        if cf_key in contact_keys:
            contact_custom[cf_key] = value
        if cf_key in lead_keys:
            lead_custom[cf_key] = value
    return contact_custom, lead_custom


async def _commit_rows(
    *,
    org_id: uuid.UUID,
    mapping: dict[str, Optional[str]],
    rows_iter,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Walk the parsed-row iterator and create one contact+lead per row.

    Each row's writes happen in their own session/transaction so a
    single bad row doesn't roll back the batch. The error list buffers
    failed rows for the per-import error CSV.
    """
    imported = duplicates = errors = 0
    error_rows: list[dict[str, Any]] = []

    # Load custom-field routing once per import — every row reuses it.
    contact_cf_keys, lead_cf_keys = await _load_custom_field_routing(org_id)

    for parsed in rows_iter:
        mapped = parsed.mapped
        full_name = (mapped.get("contact.full_name") or "").strip()
        phone = mapped.get("contact.phone")
        email = mapped.get("contact.email")

        if not full_name:
            errors += 1
            error_rows.append(
                _make_error_row(
                    parsed, "missing required field 'contact.full_name'"
                )
            )
            continue

        contact_custom, lead_custom = _split_custom_data(
            mapped, contact_cf_keys, lead_cf_keys
        )

        try:
            async with async_session() as session:
                # Resolve contact: find-or-create. Step 6 routes the
                # final lead-creation through `ingest()`, which handles
                # the open-lead dedup + round-robin assignment uniformly
                # across all five channels.
                existing_contact_id = await find_existing_contact(
                    session, org_id=org_id, phone=phone, email=email
                )
                if existing_contact_id is not None:
                    contact_id = existing_contact_id
                else:
                    contact_payload = ContactCreate(
                        full_name=full_name,
                        phone=phone,
                        email=email,
                        source=mapped.get("contact.source"),
                        notes=mapped.get("contact.notes"),
                        custom_data=contact_custom,
                    )
                    contact = await create_contact(
                        session,
                        org_id=org_id,
                        payload=contact_payload,
                        require_all_required=False,
                    )
                    contact_id = contact.id

                lead_payload = LeadCreate(
                    contact_id=contact_id,
                    pipeline_stage=mapped.get("lead.pipeline_stage"),
                    budget=_coerce_decimal(mapped.get("lead.budget")),
                    expected_close_date=_coerce_date(
                        mapped.get("lead.expected_close_date")
                    ),
                    custom_data=lead_custom,
                    source=LeadSource.bulk_import,
                )
                result = await ingest_lead(
                    session,
                    org_id=org_id,
                    source=LeadSource.bulk_import,
                    contact_id=contact_id,
                    lead_payload=lead_payload,
                )
                if result.action == "merged":
                    # `duplicates_skipped` keeps its original meaning
                    # from the operator's POV: "no new lead landed in
                    # the kanban for this row". Pre-Step-6, this fired
                    # for any contact dedup; post-Step-6, it fires
                    # when an OPEN lead already exists for the contact
                    # (which is the more precise UX intent — the
                    # existing lead got a touchpoint activity instead).
                    duplicates += 1
                else:
                    imported += 1
        except Exception as exc:
            errors += 1
            error_rows.append(_make_error_row(parsed, _format_exc(exc)))

    return (
        {
            "imported": imported,
            "duplicates_skipped": duplicates,
            "errors": errors,
        },
        error_rows,
    )


def _coerce_decimal(value: Optional[str]):
    """Parse a money-ish string into a Decimal. Returns None on blank;
    raises on parse failure so the row lands in the error CSV."""
    if value is None or value == "":
        return None
    from decimal import Decimal

    cleaned = value.replace(",", "").replace("₹", "").strip()
    return Decimal(cleaned)


def _coerce_date(value: Optional[str]):
    """Parse YYYY-MM-DD (or ISO with time) into a `date`. None if blank.
    Raises on malformed input so the row goes to errors."""
    if value is None or value == "":
        return None
    from datetime import date as _date

    try:
        return _date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError(f"invalid date {value!r} (expected YYYY-MM-DD)") from exc


def _format_exc(exc: Exception) -> str:
    """Squeeze a Pydantic/Validation/SQL error into one error-CSV cell."""
    text = str(exc).splitlines()[0]
    return text[:500]


def _make_error_row(parsed: ParsedRow, message: str) -> dict[str, Any]:
    """Build the dict the error CSV writer will dump as one CSV row."""
    return {
        "row_number": parsed.row_number,
        "raw": parsed.raw,
        "error": message,
    }


async def _write_error_csv(
    *,
    org_id: uuid.UUID,
    import_id: uuid.UUID,
    header: HeaderInfo,
    error_rows: list[dict[str, Any]],
) -> str:
    """Write the per-import errors CSV via the storage backend.

    Column order matches the source CSV exactly, then appends
    `__row_number` + `__error` so a rep can fix the file in place and
    re-upload without column re-shuffling.
    """
    buf = io.StringIO()
    columns = header.columns + ["__row_number", "__error"]
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in error_rows:
        out = dict(row["raw"])
        out["__row_number"] = row["row_number"]
        out["__error"] = row["error"]
        writer.writerow(out)
    blob = buf.getvalue().encode("utf-8")

    storage_path = f"{org_id}/imports/{import_id}/errors.csv"
    get_storage().put(storage_path, blob, content_type="text/csv")
    return storage_path


async def _mark_failed(import_id: uuid.UUID, error_message: str) -> None:
    """Transition the row to `failed` with a counts payload that
    carries the catastrophic error message for the UI to surface."""
    async with async_session() as session:
        row = (
            await session.execute(
                select(LeadImport).where(LeadImport.id == import_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return
        row.status = LeadImportStatus.failed
        row.counts = {
            "imported": 0,
            "duplicates_skipped": 0,
            "errors": 0,
            "fatal_error": error_message,
        }
        await session.commit()


__all__ = ["HAS_CELERY", "process_lead_import", "process_lead_import_async"]
