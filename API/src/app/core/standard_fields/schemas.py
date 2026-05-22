"""Pydantic v2 schemas for `StandardFieldOverride`.

Only presentational shape lives here. Per-field `overridable_props`
enforcement is dynamic against the code-defined registry and happens
in the service layer at upsert time — Pydantic alone can't express
"this prop is allowed only if the field's registry def lists it."
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StandardFieldOverrideIn(BaseModel):
    """PUT body. Every key is optional — only non-None entries are written.

    Setting a value to NULL via this surface is not supported; to clear
    an override, DELETE the row (the field then inherits the registry
    default).
    """

    label: str | None = Field(default=None, max_length=255)
    placeholder: str | None = Field(default=None, max_length=255)
    help_text: str | None = None
    is_required: bool | None = None
    is_hidden: bool | None = None
    min_value: float | None = None
    max_value: float | None = None
    step_value: float | None = None
    display_order: int | None = Field(default=None, ge=0, le=999)


class StandardFieldOverrideOut(BaseModel):
    """List / detail row. Mirrors the DB columns, plus identity fields."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entity: str
    field_key: str

    label: str | None = None
    placeholder: str | None = None
    help_text: str | None = None
    is_required: bool | None = None
    is_hidden: bool | None = None
    min_value: float | None = None
    max_value: float | None = None
    step_value: float | None = None
    display_order: int | None = None

    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None = None
    updated_by: uuid.UUID | None = None


class StandardFieldOverrideListResponse(BaseModel):
    items: list[StandardFieldOverrideOut]
    total: int
