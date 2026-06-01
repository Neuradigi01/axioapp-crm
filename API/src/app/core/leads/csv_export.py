"""Streaming CSV export for the leads list endpoint.

The endpoint reuses the same filter pipeline as ``list_leads`` (no
pagination — the caller wants every matching row), runs the query in
batches of ``_BATCH_SIZE`` ORDER-BY-id ASC, and yields one CSV chunk
per batch.

Columns: stable set of lead-direct fields + ``contact_name`` /
``contact_phone`` / ``contact_email`` from the always-joined contact +
one column per active custom field definition for the org. Phone
columns get an Excel-safe ``="+91..."`` prefix so spreadsheet apps
don't strip leading zeros.

Server-side hard cap ``EXPORT_CSV_MAX_ROWS`` (50000) — beyond that we
422 with a "narrow the filter" message. Matches the contacts export
precedent so the FE error-handling stays uniform.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime, timezone
from typing import AsyncIterator, Iterable, Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from src.app.core.contacts.models import Contact
from src.app.core.custom_fields.models import CustomFieldDefinition
from src.app.core.leads.models import Lead


EXPORT_CSV_MAX_ROWS = 50_000
_BATCH_SIZE = 1_000


_BASE_COLUMNS: Sequence[str] = (
    "id",
    "contact_name",
    "contact_phone",
    "contact_email",
    "status",
    "source",
    "pipeline_stage",
    "assigned_to_id",
    "lead_score",
    "budget",
    "expected_close_date",
    "last_activity_at",
    "lost_reason",
    "lost_reason_other",
    "created_at",
    "updated_at",
)


async def resolve_custom_columns(
    session: AsyncSession,
) -> list[str]:
    """Sorted list of lead-scoped custom-field keys, used both as CSV
    columns and as the whitelist for filter-DSL ``custom_data.<key>``
    clauses."""
    result = await session.execute(
        select(CustomFieldDefinition.field_key)
        .where(CustomFieldDefinition.entity_type == "lead")
        .order_by(CustomFieldDefinition.field_key)
    )
    return [row[0] for row in result.all()]


async def export_rows(
    session: AsyncSession,
    *,
    where_clause: ColumnElement | None,
    needs_contact_join: bool,
) -> AsyncIterator[bytes]:
    """Stream the filtered set as CSV bytes.

    Caller hands us the same boolean WHERE expression used by the
    paginated list (and a hint as to whether it already needs the
    Contact JOIN). We apply a row cap up front via COUNT-first, then
    iterate id-ordered batches of ``_BATCH_SIZE`` rows.
    """
    base_filters = [where_clause] if where_clause is not None else []

    count_stmt = select(func.count()).select_from(Lead)
    if needs_contact_join:
        count_stmt = count_stmt.join(Contact, Lead.contact_id == Contact.id)
    if base_filters:
        count_stmt = count_stmt.where(*base_filters)
    total = int((await session.execute(count_stmt)).scalar_one())
    if total > EXPORT_CSV_MAX_ROWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"export would return {total} rows "
                f"(cap {EXPORT_CSV_MAX_ROWS}); narrow the filter and try again"
            ),
        )

    custom_columns = await resolve_custom_columns(session)
    header = list(_BASE_COLUMNS) + [f"custom_{k}" for k in custom_columns]

    # --- header chunk ---
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    yield buf.getvalue().encode("utf-8")
    buf.seek(0)
    buf.truncate()

    last_id: uuid.UUID | None = None
    while True:
        stmt = (
            select(Lead, Contact)
            .join(Contact, Lead.contact_id == Contact.id)
            .order_by(Lead.id)
            .limit(_BATCH_SIZE)
        )
        if base_filters:
            stmt = stmt.where(*base_filters)
        if last_id is not None:
            stmt = stmt.where(Lead.id > last_id)

        batch = (await session.execute(stmt)).all()
        if not batch:
            break

        for lead, contact in batch:
            writer.writerow(_row_values(lead, contact, custom_columns))
            last_id = lead.id
        yield buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate()

        if len(batch) < _BATCH_SIZE:
            break


def _row_values(
    lead: Lead, contact: Contact, custom_columns: Iterable[str]
) -> list[str]:
    row: list[str] = [
        str(lead.id),
        contact.full_name or "",
        _excel_safe_phone(contact.phone),
        contact.email or "",
        lead.status.value,
        lead.source.value,
        lead.pipeline_stage or "",
        str(lead.assigned_to_id) if lead.assigned_to_id is not None else "",
        str(lead.lead_score),
        str(lead.budget) if lead.budget is not None else "",
        _iso(lead.expected_close_date),
        _iso(lead.last_activity_at),
        lead.lost_reason or "",
        lead.lost_reason_other or "",
        _iso(lead.created_at),
        _iso(lead.updated_at),
    ]
    cd = lead.custom_data or {}
    for key in custom_columns:
        value = cd.get(key)
        if value is None:
            row.append("")
        elif isinstance(value, (list, tuple)):
            row.append("|".join(str(v) for v in value))
        elif isinstance(value, bool):
            row.append("true" if value else "false")
        else:
            row.append(str(value))
    return row


def _excel_safe_phone(value: str | None) -> str:
    """Prefix phone with ``="..."`` so Excel renders the literal E.164
    value instead of dropping the leading ``+`` and any trailing zeros."""
    if not value:
        return ""
    cleaned = value.replace('"', "")
    return f'="{cleaned}"'


def _iso(value: datetime | date | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return value.isoformat()


def export_filename(org_slug: str) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return f"leads-{org_slug}-{today}.csv"


__all__ = [
    "EXPORT_CSV_MAX_ROWS",
    "export_filename",
    "export_rows",
    "resolve_custom_columns",
]
