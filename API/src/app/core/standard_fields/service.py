"""Service layer for `standard_field_overrides`.

Responsibilities the router does not duplicate:

1. **Registry-contract enforcement.** Every PUT consults
   `standard_fields.registry.get(entity, field_key)` and rejects any
   payload prop that is not in that field's `overridable_props`. The
   payload-key → registry-prop mapping is the only place that names
   bridge (e.g. `is_required` → `"required"`).

2. **Audit emission.** `settings.standard_field_override.updated` on
   every upsert and `settings.standard_field_override.reset` on every
   delete, with before/after snapshots.

3. **Tenant scoping.** The ORM tenant filter (`do_orm_execute`)
   auto-restricts SELECTs by `org_id`. Writes still receive `org_id`
   explicitly so an unset request context cannot accidentally insert a
   row into the wrong tenant.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.shared.audit import log_entity_change
from src.app.core.standard_fields import data_access as _da
from src.app.core.standard_fields import registry as field_registry
from src.app.core.standard_fields.models import StandardFieldOverride
from src.app.core.standard_fields.schemas import (
    StandardFieldOverrideIn,
    StandardFieldRendered,
)


# Payload field name → registry `overridable_props` token. The two
# vocabularies differ slightly (`is_required` vs `"required"`) — this
# is the only place that maps between them.
_PAYLOAD_PROP_MAP: dict[str, str] = {
    "label": "label",
    "placeholder": "placeholder",
    "help_text": "help",
    "is_required": "required",
    "is_hidden": "hidden",
    "min_value": "min",
    "max_value": "max",
    "step_value": "step",
    "display_order": "display_order",
}


# Payload column → DB column. Same name in every case today but kept
# explicit so a future rename doesn't silently break the upsert.
_DB_COLUMNS: tuple[str, ...] = tuple(_PAYLOAD_PROP_MAP.keys())


def _snapshot(row: StandardFieldOverride) -> dict[str, Any]:
    """JSONB-friendly diff payload for audit `before` / `after`."""
    return {
        "label": row.label,
        "placeholder": row.placeholder,
        "help_text": row.help_text,
        "is_required": row.is_required,
        "is_hidden": row.is_hidden,
        "min_value": float(row.min_value) if row.min_value is not None else None,
        "max_value": float(row.max_value) if row.max_value is not None else None,
        "step_value": float(row.step_value) if row.step_value is not None else None,
        "display_order": row.display_order,
    }


def _validate_payload_against_registry(
    *, entity: str, field_key: str, payload: StandardFieldOverrideIn
) -> None:
    """Raise 404 / 422 if registry rejects the payload."""
    definition = field_registry.get(entity, field_key)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"standard field {entity}.{field_key} not in registry",
        )

    allowed = definition.overridable_props
    errors: list[str] = []
    for payload_key, prop_token in _PAYLOAD_PROP_MAP.items():
        if getattr(payload, payload_key) is None:
            continue
        if prop_token not in allowed:
            errors.append(
                f"{payload_key} not overridable for {entity}.{field_key}"
            )

    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": errors},
        )


async def list_for_org(
    session: AsyncSession, *, org_id: uuid.UUID
) -> tuple[list[StandardFieldOverride], int]:
    """All overrides for the active org."""
    return await _da.list_overrides_for_org(session, org_id=org_id)


async def list_for_entity(
    session: AsyncSession, *, org_id: uuid.UUID, entity: str
) -> tuple[list[StandardFieldOverride], int]:
    """Overrides for one entity. Used by the per-entity list endpoint."""
    rows = await _da.list_overrides_for_entity(
        session, org_id=org_id, entity=entity
    )
    return rows, len(rows)


async def upsert(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    entity: str,
    field_key: str,
    payload: StandardFieldOverrideIn,
    actor_id: uuid.UUID | None,
) -> StandardFieldOverride:
    """Insert or update one override row.

    Validates against the registry first (404 / 422 if rejected), then
    issues `INSERT ... ON CONFLICT (org_id, entity, field_key) DO UPDATE`.
    Audit event `settings.standard_field_override.updated` fires with a
    `{before, after}` diff.
    """
    _validate_payload_against_registry(
        entity=entity, field_key=field_key, payload=payload
    )

    existing = await _da.get_override_by_keys(
        session, org_id=org_id, entity=entity, field_key=field_key
    )
    before = _snapshot(existing) if existing is not None else None

    payload_dict = payload.model_dump(exclude_none=True)

    insert_values: dict[str, Any] = {
        "org_id": org_id,
        "entity": entity,
        "field_key": field_key,
        "created_by": actor_id,
        "updated_by": actor_id,
        **payload_dict,
    }
    update_values: dict[str, Any] = {
        **payload_dict,
        "updated_by": actor_id,
        "updated_at": func.now(),
    }

    await _da.upsert_override(
        session,
        insert_values=insert_values,
        update_values=update_values,
    )
    await session.commit()

    row = await _da.get_override_by_keys(
        session, org_id=org_id, entity=entity, field_key=field_key
    )
    assert row is not None  # upsert just guaranteed this row

    await log_entity_change(
        action="settings.standard_field_override.updated",
        entity_type="standard_field_override",
        entity_id=row.id,
        before=before,
        after=_snapshot(row),
    )
    return row


async def reset(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    entity: str,
    field_key: str,
) -> None:
    """Remove the override row → the field inherits registry defaults."""
    definition = field_registry.get(entity, field_key)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"standard field {entity}.{field_key} not in registry",
        )

    existing = await _da.get_override_by_keys(
        session, org_id=org_id, entity=entity, field_key=field_key
    )
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no override set for {entity}.{field_key}",
        )

    snapshot = _snapshot(existing)
    snapshot_id = existing.id

    await _da.delete_override(
        session, org_id=org_id, entity=entity, field_key=field_key
    )
    await session.commit()

    await audit.log(
        "settings.standard_field_override.reset",
        entity_type="standard_field_override",
        entity_id=snapshot_id,
        before=snapshot,
    )


# ---------------------------------------------------------------------------
# Merge: registry defaults + override row → `StandardFieldRendered`
#
# Every form modal calls `render_for_entity` on open. The merge is the
# only logic outside the test path that matters here.
# ---------------------------------------------------------------------------


# Override columns to consider when determining `is_overridden`. Order is
# stable for diffing/logging; values are not significant.
_OVERRIDE_COLUMNS: tuple[str, ...] = (
    "label",
    "placeholder",
    "help_text",
    "is_required",
    "is_hidden",
    "min_value",
    "max_value",
    "step_value",
    "display_order",
)


def _coalesce_numeric(
    override_value: Any, registry_value: float | None
) -> float | None:
    """Pick the override (cast Decimal → float) if set, else the registry default."""
    if override_value is None:
        return registry_value
    return float(override_value)


def _merge(
    definition: field_registry.StandardFieldDef,
    override: StandardFieldOverride | None,
) -> StandardFieldRendered:
    """Coalesce one field. Pure function — no DB or context dependency."""
    o = override  # alias for readability below

    return StandardFieldRendered(
        entity=definition.entity,
        field_key=definition.field_key,
        field_type=definition.field_type,
        label=(o.label if o and o.label is not None else definition.default_label),
        placeholder=(
            o.placeholder if o and o.placeholder is not None
            else definition.default_placeholder
        ),
        help_text=(
            o.help_text if o and o.help_text is not None
            else definition.default_help
        ),
        is_required=(
            o.is_required if o and o.is_required is not None
            else definition.default_required
        ),
        is_hidden=(o.is_hidden if o and o.is_hidden is not None else False),
        min_value=_coalesce_numeric(
            o.min_value if o else None, definition.default_min
        ),
        max_value=_coalesce_numeric(
            o.max_value if o else None, definition.default_max
        ),
        step_value=_coalesce_numeric(
            o.step_value if o else None, definition.default_step
        ),
        display_order=(
            o.display_order if o and o.display_order is not None
            else definition.default_display_order
        ),
        backend_required=definition.backend_required,
        backend_validators=list(definition.backend_validators),
        is_overridden=_is_overridden(o),
        overridable_props=sorted(definition.overridable_props),
    )


def _is_overridden(override: StandardFieldOverride | None) -> bool:
    """True iff an override row exists with at least one non-NULL column."""
    if override is None:
        return False
    return any(getattr(override, col) is not None for col in _OVERRIDE_COLUMNS)


class EntityNotInRegistry(HTTPException):
    """Raised when `render_for_entity` is called with an unknown entity."""

    def __init__(self, entity: str) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"entity {entity!r} not in standard-fields registry",
        )


async def _fetch_overrides_map(
    session: AsyncSession, *, org_id: uuid.UUID, entity: str
) -> dict[str, StandardFieldOverride]:
    """One SELECT, one dict keyed by `field_key`. Avoids N+1 in
    `render_for_entity`."""
    rows = await _da.list_overrides_for_entity(
        session, org_id=org_id, entity=entity
    )
    return {row.field_key: row for row in rows}


async def render_for_entity(
    session: AsyncSession, *, org_id: uuid.UUID, entity: str
) -> list[StandardFieldRendered]:
    """Return registry defaults merged with the org's overrides for `entity`."""
    registry_defs = field_registry.list_for_entity(entity)
    if not registry_defs:
        raise EntityNotInRegistry(entity)

    overrides = await _fetch_overrides_map(session, org_id=org_id, entity=entity)

    indexed: list[tuple[int, int, StandardFieldRendered]] = []
    for idx, definition in enumerate(registry_defs):
        rendered = _merge(definition, overrides.get(definition.field_key))
        indexed.append((rendered.display_order, idx, rendered))

    indexed.sort(key=lambda triple: (triple[0], triple[1]))
    return [rendered for _, _, rendered in indexed]
