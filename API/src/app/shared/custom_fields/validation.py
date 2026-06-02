"""Shared validator for the per-org ``custom_data`` JSONB payload.

The same `_load_field_defs` + `_coerce_value` + `_validate_custom_data`
trio used to live in every entity's service module (contacts, leads,
appointments, catalog, walk_ins). The logic was byte-identical except
for the `entity_type` string baked into each copy. This module is the
extracted single source.

Public entry point: :func:`validate_custom_data`. Tenant scoping flows
through the global ORM filter on :class:`CustomFieldDefinition`, so the
caller doesn't pass an ``org_id`` — the active request context supplies
it transparently.

Error-message shapes are preserved bit-identically with the
pre-refactor versions so the frontend dynamic-form renderer (which
parses these 422 details directly) keeps working:

    - unknown keys      → ``"custom_data contains keys not defined for entity '<entity>': […]"``
    - per-key mismatch  → ``"custom_data.<key>: expected …"`` / ``"invalid ISO date"`` / etc.
    - missing required  → ``"custom_data missing required keys: […]"``
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.custom_fields.models import CustomFieldDefinition, FieldType


def _coerce_value(field_type: FieldType, key: str, value: Any) -> Any:
    """Validate / coerce a single ``custom_data`` value. Raises 422 on mismatch."""
    if value is None:
        return None

    if field_type in (FieldType.text, FieldType.phone, FieldType.email, FieldType.select):
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected string",
            )
        return value

    if field_type is FieldType.multiselect:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected list of strings",
            )
        return value

    if field_type in (FieldType.number, FieldType.currency):
        # `bool` is a subclass of `int` in Python — reject it explicitly so
        # `True` doesn't sneak past a number check.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected number",
            )
        return value

    if field_type is FieldType.boolean:
        if not isinstance(value, bool):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected boolean",
            )
        return value

    if field_type is FieldType.date:
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected ISO date string",
            )
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: invalid ISO date",
            ) from exc
        return value

    if field_type is FieldType.datetime:
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected ISO datetime string",
            )
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: invalid ISO datetime",
            ) from exc
        return value

    # `FieldType` is an exhaustive enum; reaching here means a new type
    # was added without extending this switch. Fail loudly.
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"unhandled field_type {field_type!r}",
    )


async def _load_field_defs(
    session: AsyncSession, entity_type: str
) -> dict[str, CustomFieldDefinition]:
    result = await session.execute(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.entity_type == entity_type
        )
    )
    return {row.field_key: row for row in result.scalars()}


async def validate_custom_data(
    session: AsyncSession,
    *,
    entity_type: str,
    payload: dict[str, Any],
    require_all_required: bool,
) -> dict[str, Any]:
    """Validate ``payload`` against the org's ``custom_field_definitions``
    for ``entity_type``.

    ``require_all_required=True`` on create paths; ``False`` on partial
    update paths. Returns a sanitized copy (values coerced where
    applicable).
    """
    defs = await _load_field_defs(session, entity_type)

    unknown = set(payload) - set(defs)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "custom_data contains keys not defined for entity "
                f"'{entity_type}': {sorted(unknown)}"
            ),
        )

    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        cleaned[key] = _coerce_value(defs[key].field_type, key, value)

    if require_all_required:
        missing = [
            key
            for key, defn in defs.items()
            if defn.is_required and (key not in cleaned or cleaned[key] is None)
        ]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data missing required keys: {sorted(missing)}",
            )

    return cleaned
