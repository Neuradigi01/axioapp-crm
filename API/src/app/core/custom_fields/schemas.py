"""Pydantic v2 schemas for `custom_field_definitions`.

`field_key` validates against the SQL-safe identifier shape the master
prompt mandates: lowercase ASCII letter + 1–49 of letters/digits/`_`.
`select`/`multiselect` types require an `options.choices` list of
non-empty strings; that validation lives here so the router rejects
bad payloads before reaching the service.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from src.app.core.custom_fields.models import FieldSource, FieldType
from src.app.shared.schemas import ORMModel, TimestampedOrgScopedOut


FIELD_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,49}$")
_FIELD_KEY_HINT = (
    "must be lowercase, start with a letter, and use only letters, digits, "
    "or underscores (2–50 chars total)"
)


def _validate_options(field_type: FieldType, options: dict[str, Any] | None) -> None:
    """Raise ValueError if `options` doesn't match the constraints for `field_type`.

    Today the only typed constraint is on `select`/`multiselect`: they
    must declare `choices` — a non-empty list of non-empty strings —
    so the renderer has something to draw.
    """
    if field_type in (FieldType.select, FieldType.multiselect):
        if not options or not isinstance(options.get("choices"), list):
            raise ValueError(
                f"field_type {field_type.value!r} requires options.choices "
                "as a non-empty list of strings"
            )
        choices = options["choices"]
        if not choices or not all(
            isinstance(c, str) and c.strip() for c in choices
        ):
            raise ValueError(
                "options.choices must be a non-empty list of non-empty strings"
            )


class CustomFieldCreate(BaseModel):
    entity_type: str = Field(min_length=1, max_length=64)
    field_key: str = Field(min_length=2, max_length=50)
    field_label: str = Field(min_length=1, max_length=128)
    field_type: FieldType
    options: dict[str, Any] | None = None
    is_required: bool = False
    is_hidden: bool = False
    display_order: int = 0
    validation: dict[str, Any] | None = None

    @field_validator("field_key")
    @classmethod
    def _check_field_key(cls, value: str) -> str:
        if not FIELD_KEY_PATTERN.match(value):
            raise ValueError(f"field_key {_FIELD_KEY_HINT}")
        return value

    @field_validator("entity_type")
    @classmethod
    def _check_entity_type(cls, value: str) -> str:
        # entity_type uses the same identifier shape as field_key — it
        # corresponds to a backend module name (e.g. "contact",
        # "appointment"). Keep validation symmetrical with field_key
        # so future render endpoints can rely on safe URL fragments.
        if not FIELD_KEY_PATTERN.match(value):
            raise ValueError(f"entity_type {_FIELD_KEY_HINT}")
        return value

    @model_validator(mode="after")
    def _check_options(self) -> "CustomFieldCreate":
        _validate_options(self.field_type, self.options)
        return self


class CustomFieldUpdate(BaseModel):
    """All fields optional. Source-rule enforcement lives in the service."""

    field_label: str | None = Field(default=None, min_length=1, max_length=128)
    is_required: bool | None = None
    is_hidden: bool | None = None
    display_order: int | None = None
    options: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None


class CustomFieldOut(TimestampedOrgScopedOut):
    id: uuid.UUID
    entity_type: str
    field_key: str
    field_label: str
    field_type: FieldType
    options: dict[str, Any] | None
    is_required: bool
    is_hidden: bool
    display_order: int
    source: FieldSource
    pack_id: str | None
    validation: dict[str, Any] | None


class CustomFieldRenderItem(ORMModel):
    """Slim shape for the `/render` endpoint — what the form needs, no more."""

    field_key: str
    field_label: str
    field_type: FieldType
    options: dict[str, Any] | None
    is_required: bool
    display_order: int
    validation: dict[str, Any] | None
