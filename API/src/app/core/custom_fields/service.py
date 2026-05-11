"""Service layer for `custom_field_definitions`.

Every write path goes through one of `create_user_field`,
`create_managed_field` (system/pack callers only), `update_field`, or
`delete_field`. The source-rule policy lives in this module and the
router does not duplicate it — that keeps rule enforcement testable in
one place.

Audit events (`custom_fields.created`, `.updated`, `.deleted`) fire
inside each write path so callers don't need to remember.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.custom_fields.models import (
    CustomFieldDefinition,
    FieldSource,
    FieldType,
)
from src.app.core.custom_fields.schemas import (
    CustomFieldCreate,
    CustomFieldUpdate,
    _validate_options,
)


class CustomFieldError(HTTPException):
    """Single 4xx exception type for source-rule violations.

    Status codes are inlined at each raise site so the message is
    consistent across the module.
    """


def _snapshot(field: CustomFieldDefinition) -> dict[str, Any]:
    """JSONB-friendly snapshot of a definition for audit `before`/`after`."""
    return {
        "id": str(field.id),
        "entity_type": field.entity_type,
        "field_key": field.field_key,
        "field_label": field.field_label,
        "field_type": field.field_type.value,
        "options": field.options,
        "is_required": field.is_required,
        "is_hidden": field.is_hidden,
        "display_order": field.display_order,
        "source": field.source.value,
        "pack_id": field.pack_id,
        "validation": field.validation,
    }


async def get_field(
    session: AsyncSession, field_id: uuid.UUID
) -> CustomFieldDefinition | None:
    """Return a single definition by id, scoped to the active tenant."""
    result = await session.execute(
        select(CustomFieldDefinition).where(CustomFieldDefinition.id == field_id)
    )
    return result.scalar_one_or_none()


async def list_fields(
    session: AsyncSession,
    *,
    entity_type: str,
    include_hidden: bool = False,
) -> list[CustomFieldDefinition]:
    """List definitions for one entity, ordered for stable rendering."""
    stmt = select(CustomFieldDefinition).where(
        CustomFieldDefinition.entity_type == entity_type
    )
    if not include_hidden:
        stmt = stmt.where(CustomFieldDefinition.is_hidden.is_(False))
    stmt = stmt.order_by(
        CustomFieldDefinition.display_order,
        CustomFieldDefinition.field_key,
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def render_fields(
    session: AsyncSession, *, entity_type: str
) -> list[CustomFieldDefinition]:
    """Visible, ordered list used by the frontend form renderer."""
    return await list_fields(session, entity_type=entity_type, include_hidden=False)


async def create_user_field(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: CustomFieldCreate,
) -> CustomFieldDefinition:
    """Public create path: always stamps `source=user`. Pack/system rows
    use ``create_managed_field`` from their respective installers.
    """
    field = CustomFieldDefinition(
        org_id=org_id,
        entity_type=payload.entity_type,
        field_key=payload.field_key,
        field_label=payload.field_label,
        field_type=payload.field_type,
        options=payload.options,
        is_required=payload.is_required,
        is_hidden=payload.is_hidden,
        display_order=payload.display_order,
        source=FieldSource.user,
        pack_id=None,
        validation=payload.validation,
    )
    session.add(field)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"custom field '{payload.field_key}' already exists for "
                f"entity '{payload.entity_type}'"
            ),
        ) from exc
    await session.refresh(field)

    await audit.log(
        "custom_fields.created",
        entity_type="custom_field_definition",
        entity_id=field.id,
        after=_snapshot(field),
    )
    return field


async def create_managed_field(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    source: FieldSource,
    pack_id: str | None,
    entity_type: str,
    field_key: str,
    field_label: str,
    field_type: FieldType,
    options: dict[str, Any] | None = None,
    is_required: bool = False,
    is_hidden: bool = False,
    display_order: int = 0,
    validation: dict[str, Any] | None = None,
) -> CustomFieldDefinition:
    """Create a `system` or `pack` field. Not exposed over HTTP — callers
    are the core seed runner and the pack installer.
    """
    if source is FieldSource.user:
        raise CustomFieldError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="create_managed_field requires source=system or source=pack",
        )
    if source is FieldSource.pack and not pack_id:
        raise CustomFieldError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pack fields must declare a pack_id",
        )

    _validate_options(field_type, options)

    field = CustomFieldDefinition(
        org_id=org_id,
        entity_type=entity_type,
        field_key=field_key,
        field_label=field_label,
        field_type=field_type,
        options=options,
        is_required=is_required,
        is_hidden=is_hidden,
        display_order=display_order,
        source=source,
        pack_id=pack_id,
        validation=validation,
    )
    session.add(field)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"custom field '{field_key}' already exists for "
                f"entity '{entity_type}'"
            ),
        ) from exc
    await session.refresh(field)

    await audit.log(
        "custom_fields.created",
        entity_type="custom_field_definition",
        entity_id=field.id,
        after=_snapshot(field),
    )
    return field


async def update_field(
    session: AsyncSession,
    *,
    field_id: uuid.UUID,
    payload: CustomFieldUpdate,
) -> CustomFieldDefinition:
    """Apply an update respecting the source rules.

    Rules:
      - `system`: label, display_order, is_required, validation editable;
        is_hidden NOT editable (system fields are always visible by intent).
      - `pack`:   label, display_order, is_hidden, validation editable;
        is_required NOT editable (pack defines its own requirements).
      - `user`:   anything in the update payload may change.

    `field_key`, `field_type`, `source`, `pack_id` are immutable on every
    source — the Update schema doesn't accept them.
    """
    field = await get_field(session, field_id)
    if field is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="custom field not found",
        )

    before = _snapshot(field)
    changes = payload.model_dump(exclude_unset=True)

    if field.source is FieldSource.system:
        forbidden = set(changes) - {
            "field_label",
            "display_order",
            "is_required",
            "validation",
        }
        if forbidden:
            raise CustomFieldError(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "system fields only allow updates to "
                    f"label/display_order/is_required/validation (got {sorted(forbidden)})"
                ),
            )
    elif field.source is FieldSource.pack:
        forbidden = set(changes) - {
            "field_label",
            "display_order",
            "is_hidden",
            "validation",
        }
        if forbidden:
            raise CustomFieldError(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "pack fields only allow updates to "
                    f"label/display_order/is_hidden/validation (got {sorted(forbidden)})"
                ),
            )

    if "options" in changes:
        # User-source only — system/pack reject options edits above.
        _validate_options(field.field_type, changes["options"])

    for key, value in changes.items():
        setattr(field, key, value)
    await session.commit()
    await session.refresh(field)

    await audit.log(
        "custom_fields.updated",
        entity_type="custom_field_definition",
        entity_id=field.id,
        before=before,
        after=_snapshot(field),
    )
    return field


async def delete_field(
    session: AsyncSession, *, field_id: uuid.UUID
) -> None:
    """Delete a definition. Only `source=user` is deletable via HTTP."""
    field = await get_field(session, field_id)
    if field is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="custom field not found",
        )

    if field.source is not FieldSource.user:
        raise CustomFieldError(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"{field.source.value} fields cannot be deleted; hide it "
                "with is_hidden=true instead"
            ),
        )

    before = _snapshot(field)
    field_uuid = field.id
    await session.delete(field)
    await session.commit()

    await audit.log(
        "custom_fields.deleted",
        entity_type="custom_field_definition",
        entity_id=field_uuid,
        before=before,
    )
