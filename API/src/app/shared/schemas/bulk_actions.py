"""Shared request and result shapes for bulk-action endpoints.

Each list-page bulk operation (reassign / delete / add-tag) used to
ship a per-entity Pydantic class with byte-identical fields:

    class XBulkReassign(BaseModel):
        ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
        assigned_to_id: uuid.UUID | None = None
        note: str | None = Field(default=None, max_length=500)
        model_config = ConfigDict(str_strip_whitespace=True)

This module is the single source. Per-entity ``schemas.py`` files
re-export under the old names as type aliases so router signatures
and FE payloads are unchanged.

OpenAPI schema name note: type aliases collapse the per-entity names
(``ContactBulkReassign``, ``LeadBulkReassign``, ``TaskBulkReassign``)
to a single ``BulkReassign`` schema in ``/openapi.json``. JSON payload
shape is unchanged — FE clients keep working.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


# Per-request id-count cap. Aligns with the rate-limit guard on
# `paginate(size <= 200)` in `app.shared.db.pagination` — a bulk request
# can never touch more rows than a single page exposes.
_MAX_IDS = 200

# Tag length cap matches the contacts module's ``_TAG_MAX = 64``.
_TAG_MAX = 64


class BulkIds(BaseModel):
    """Base shape: a non-empty list of entity ids capped at ``_MAX_IDS``."""

    ids: list[uuid.UUID] = Field(min_length=1, max_length=_MAX_IDS)


# --- Request shapes ------------------------------------------------------


class BulkReassign(BulkIds):
    """Bulk reassign owner. ``assigned_to_id=None`` clears the owner.
    Entities whose ``assigned_to_id`` is NOT NULL (e.g. tasks,
    appointments) reject ``None`` at the service layer; the type stays
    optional here so the wire shape is uniform across entities."""

    assigned_to_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(str_strip_whitespace=True)


class BulkDelete(BulkIds):
    """Bulk delete by id list. No extra fields."""


class BulkAddTag(BulkIds):
    """Bulk add a single tag to N entities."""

    tag: str = Field(min_length=1, max_length=_TAG_MAX)

    model_config = ConfigDict(str_strip_whitespace=True)


# --- Result envelopes ----------------------------------------------------


class BulkReassignResult(BaseModel):
    reassigned: int


class BulkDeleteResult(BaseModel):
    deleted: int


class BulkAddTagResult(BaseModel):
    updated: int
