"""Pydantic schemas for the contact-imports API surface."""

from __future__ import annotations

import uuid
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
    mapping step — persisted onto every contact this import inserts."""

    model_config = ConfigDict(extra="forbid")

    mapping: dict[str, str]
    create_group: bool = False
    group_name: str | None = Field(default=None, max_length=255)
    opt_in_source: OptInSource | None = None


class RowError(BaseModel):
    row: int
    reason: str


class ImportDryRunOut(BaseModel):
    """Counts from the dry-run — nothing is inserted yet."""

    will_insert: int
    will_skip: int  # rows missing required fields, malformed, etc.
    duplicate_phone: int  # rows whose phone already exists
    errors: list[RowError]


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
    created_group_id: uuid.UUID | None = None


__all__ = [
    "ContactFieldTarget",
    "ImportCommitIn",
    "ImportCommitOut",
    "ImportDryRunIn",
    "ImportDryRunOut",
    "ImportUploadOut",
    "OptInSource",
    "RowError",
]
