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
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.standard_fields import registry as field_registry
from src.app.core.standard_fields.models import StandardFieldOverride
from src.app.core.standard_fields.schemas import StandardFieldOverrideIn


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
    """Raise 404 / 422 if registry rejects the payload.

    - 404 if `(entity, field_key)` not registered.
    - 422 if the payload sets any prop not in `overridable_props`.

    Only non-None payload fields count — sending the body
    `{"label": "x"}` does not "set" the other props.
    """
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
    """All overrides for the active org. Tenant scoping is automatic but
    `org_id` is passed in defensively for an explicit WHERE."""
    stmt = (
        select(StandardFieldOverride)
        .where(StandardFieldOverride.org_id == org_id)
        .order_by(StandardFieldOverride.entity, StandardFieldOverride.field_key)
    )
    rows = (await session.execute(stmt)).scalars().all()
    total = (
        await session.execute(
            select(func.count()).select_from(StandardFieldOverride).where(
                StandardFieldOverride.org_id == org_id
            )
        )
    ).scalar_one()
    return list(rows), int(total)


async def list_for_entity(
    session: AsyncSession, *, org_id: uuid.UUID, entity: str
) -> tuple[list[StandardFieldOverride], int]:
    """Overrides for one entity. Used by the per-entity list endpoint."""
    stmt = (
        select(StandardFieldOverride)
        .where(
            StandardFieldOverride.org_id == org_id,
            StandardFieldOverride.entity == entity,
        )
        .order_by(StandardFieldOverride.field_key)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return list(rows), len(rows)


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

    existing = (
        await session.execute(
            select(StandardFieldOverride).where(
                StandardFieldOverride.org_id == org_id,
                StandardFieldOverride.entity == entity,
                StandardFieldOverride.field_key == field_key,
            )
        )
    ).scalar_one_or_none()
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

    stmt = (
        pg_insert(StandardFieldOverride)
        .values(**insert_values)
        .on_conflict_do_update(
            constraint="uq_standard_field_overrides_org_entity_field",
            set_=update_values,
        )
    )
    await session.execute(stmt)
    await session.commit()

    row = (
        await session.execute(
            select(StandardFieldOverride).where(
                StandardFieldOverride.org_id == org_id,
                StandardFieldOverride.entity == entity,
                StandardFieldOverride.field_key == field_key,
            )
        )
    ).scalar_one()

    await audit.log(
        "settings.standard_field_override.updated",
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
    """Remove the override row → the field inherits registry defaults.

    404 if no row exists for `(entity, field_key)`. Validating the
    registry membership too means a caller can't DELETE-poke for the
    existence of arbitrary field keys.
    """
    definition = field_registry.get(entity, field_key)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"standard field {entity}.{field_key} not in registry",
        )

    existing = (
        await session.execute(
            select(StandardFieldOverride).where(
                StandardFieldOverride.org_id == org_id,
                StandardFieldOverride.entity == entity,
                StandardFieldOverride.field_key == field_key,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no override set for {entity}.{field_key}",
        )

    snapshot = _snapshot(existing)
    snapshot_id = existing.id

    await session.execute(
        delete(StandardFieldOverride).where(
            StandardFieldOverride.org_id == org_id,
            StandardFieldOverride.entity == entity,
            StandardFieldOverride.field_key == field_key,
        )
    )
    await session.commit()

    await audit.log(
        "settings.standard_field_override.reset",
        entity_type="standard_field_override",
        entity_id=snapshot_id,
        before=snapshot,
    )
