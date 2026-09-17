"""Pydantic schemas for the contact-imports API surface."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.app.shared.schemas import ORMModel

# Contact-field targets the operator can map a column to. Mirrors
# the Contact model's settable fields. `custom_data.<key>` is a
# future-compat target (key encoded in the mapping value, e.g.
# `"custom_data.preferred_sofa"`).
ContactFieldTarget = Literal[
    "full_name",
    "phone",
    "email",
    "source",
    "tag",  # single tag → goes into tags array
    "skip",  # explicit "don't import this column"
]


class ImportUploadOut(ORMModel):
    """Returned by `POST /upload` — gives the frontend everything it
    needs to render the column-mapping step without re-reading the
    file."""

    id: uuid.UUID
    filename: str
    row_count: int
    headers: list[str]
    suggested_mapping: dict[str, str]
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)


OptInSource = Literal[
    "form_widget",
    "bulk_import",
    "manual_entry",
    "inbound_first_message",
    "explicit_opt_in_link",
    "stop_keyword",
]


class ImportDryRunIn(BaseModel):
    """Body for `POST /{id}/dry-run`.

    `mapping` is the operator's final column → contact-field assignment.
    `create_group` + `group_name` are the optional bundling — if set,
    the commit step (separate endpoint) will create a static group from
    the successfully-inserted contacts.
    `opt_in_source` is the DPDP provenance the operator picks on the
    mapping step — persisted onto every contact this import inserts.
    `default_source` is the batch-level fallback for `contact.source`:
    when the CSV row's mapped source cell is empty (or the column isn't
    mapped at all), each inserted contact gets this value. NULL keeps
    the prior behaviour (empty stays empty)."""

    model_config = ConfigDict(extra="forbid")

    mapping: dict[str, str]
    create_group: bool = False
    group_name: str | None = Field(default=None, max_length=255)
    opt_in_source: OptInSource | None = None
    default_source: str | None = Field(default=None, max_length=64)


class RowError(BaseModel):
    """One rejected import row's forensic record.

    Existing consumers read `row` + `reason` only; `column` + `value`
    were added when the shared per-field validators (Step 1 of the
    application-updates track) were wired into the import loop, so
    operators can see *which* column tripped and *what* the offending
    value was without downloading `errors.csv`. Both remain optional
    to keep the payload additive for older UI builds.
    """

    row: int
    reason: str
    column: str | None = None
    value: str | None = None


class ImportDryRunOut(BaseModel):
    """Counts + per-row detail from the dry-run — nothing is inserted yet.

    The three per-row lists (``errors`` / ``duplicates`` / ``warnings``)
    match the three downloadable CSVs the operator gets after commit,
    so the wizard's Preview step can render exactly what the commit
    will produce. Split adopted 2026-07-30 to mirror the leads-import
    surface's 3-CSV pattern.
    """

    will_insert: int
    will_skip: int  # rows missing required fields, malformed, etc.
    # Kept for backwards compatibility with older FE builds that read
    # this instead of `duplicate_count`. Same value as `duplicate_count`.
    duplicate_phone: int
    duplicate_count: int = 0
    warning_count: int = 0
    errors: list[RowError]
    duplicates: list[RowError] = []
    warnings: list[RowError] = []


class ImportCommitIn(ImportDryRunIn):
    """Same shape as dry-run — commit re-runs the parse + insert,
    using the exact mapping the operator just previewed. Re-validation
    catches anyone who edited the spreadsheet between dry-run and
    commit (rare but possible)."""


class ImportCommitOut(BaseModel):
    id: uuid.UUID
    status: str
    row_count: int
    success_count: int
    error_count: int
    # 3-CSV parity with the leads-import surface (2026-07-30). Rows
    # that collide on phone land in ``duplicate_count`` / skipped.csv;
    # rows that imported successfully but had a value coerced (e.g.
    # tag truncation) land in ``warning_count`` / warnings.csv.
    duplicate_count: int = 0
    warning_count: int = 0
    created_group_id: uuid.UUID | None = None


class ImportListItem(ORMModel):
    """One row on the wizard's history page. Slim projection of
    ``ContactImport`` — includes the outcome counts + status so the
    page can render badges and download buttons without a second
    round-trip."""

    id: uuid.UUID
    filename: str
    row_count: int
    success_count: int
    error_count: int
    duplicate_count: int
    warning_count: int
    status: str
    created_group_id: uuid.UUID | None = None
    created_at: datetime


class ImportListResponse(BaseModel):
    """Wire response for ``GET /contacts/imports`` — mirror shape of
    :class:`LeadImportListResponse` so the FE history component is
    interchangeable between the two entities."""

    items: list[ImportListItem]
    total: int
    page: int
    size: int


__all__ = [
    "ContactFieldTarget",
    "ImportCommitIn",
    "ImportCommitOut",
    "ImportDryRunIn",
    "ImportDryRunOut",
    "ImportListItem",
    "ImportListResponse",
    "ImportUploadOut",
    "OptInSource",
    "RowError",
]
