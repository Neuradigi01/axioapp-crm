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

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.custom_fields.models import CustomFieldDefinition
from src.app.shared.custom_fields.coercion import coerce_value


async def _load_field_defs(
    session: AsyncSession, entity_type: str
) -> dict[str, CustomFieldDefinition]:
    result = await session.execute(
        select(CustomFieldDefinition).where(CustomFieldDefinition.entity_type == entity_type)
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
        cleaned[key] = coerce_value(defs[key].field_type, key, value)

    if require_all_required:
        # Hidden fields are treated as "removed from the form" — the
        # operator can't fill them in the create UI, so it would be
        # nonsense for the API to reject the same create for missing
        # them. The definitions stay in the DB (existing `custom_data`
        # payloads still coerce cleanly above); they just don't force
        # anything.
        missing = [
            key
            for key, defn in defs.items()
            if defn.is_required
            and not defn.is_hidden
            and (key not in cleaned or cleaned[key] is None)
        ]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data missing required keys: {sorted(missing)}",
            )

    return cleaned
