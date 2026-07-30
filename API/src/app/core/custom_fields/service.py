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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.custom_fields import data_access as _da
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
from src.app.shared.audit import log_entity_change


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


async def get_field(session: AsyncSession, field_id: uuid.UUID) -> CustomFieldDefinition | None:
    """Return a single definition by id, scoped to the active tenant."""
    return await _da.get_field_by_id(session, field_id)


async def list_fields(
    session: AsyncSession,
    *,
    entity_type: str,
    include_hidden: bool = False,
) -> list[CustomFieldDefinition]:
    """List definitions for one entity, ordered for stable rendering."""
    return await _da.list_fields_query(
        session, entity_type=entity_type, include_hidden=include_hidden
    )


async def render_fields(session: AsyncSession, *, entity_type: str) -> list[CustomFieldDefinition]:
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
    _da.insert_field(session, field)
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

    await log_entity_change(
        action="custom_fields.created",
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
    _da.insert_field(session, field)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"custom field '{field_key}' already exists for entity '{entity_type}'"),
        ) from exc
    await session.refresh(field)

    await log_entity_change(
        action="custom_fields.created",
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
    """Apply an update to a custom-field definition.

    Any attribute in the Update payload is editable regardless of the
    field's ``source``. Previously ``system`` and ``pack`` sources
    had per-source whitelists (e.g. pack rejected ``is_required`` +
    ``options`` edits, system rejected ``is_hidden``). Those were
    overly defensive — pack self-healing / integrity re-checks don't
    exist in this codebase, so the lock was guarding against a
    failure mode that couldn't self-correct anyway; users just got
    nagged into workarounds. Full mutability now.

    ``field_key``, ``field_type``, ``source``, ``pack_id`` are still
    immutable on every source — the Update schema itself doesn't
    accept them, so this function never has to reject them
    explicitly.

    ``options`` when supplied is still shape-validated against
    ``field_type`` (only select-type fields carry options), because
    that's a data-integrity check, not a source restriction.
    """
    field = await get_field(session, field_id)
    if field is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="custom field not found",
        )

    before = _snapshot(field)
    changes = payload.model_dump(exclude_unset=True)

    if "options" in changes:
        _validate_options(field.field_type, changes["options"])

    for key, value in changes.items():
        setattr(field, key, value)
    await session.commit()
    await session.refresh(field)

    await log_entity_change(
        action="custom_fields.updated",
        entity_type="custom_field_definition",
        entity_id=field.id,
        before=before,
        after=_snapshot(field),
    )
    return field


async def delete_field(session: AsyncSession, *, field_id: uuid.UUID) -> None:
    """Delete a custom-field definition.

    Deletable regardless of ``source``. Previously only ``source=user``
    fields could be deleted; ``system`` / ``pack`` fields were locked
    to prevent an operator from breaking pack-installed forms /
    imports / workflows that keyed off those columns. In practice the
    codebase has no pack self-healing (installers are one-way, there
    is no "pack update" / integrity re-check), so the lock was
    guarding against a failure mode that couldn't self-correct anyway
    — the operator was just being nagged into using ``is_hidden``
    instead of Delete.

    The ``source`` value is still preserved on the audit-log ``before``
    snapshot so we can trace which fields originated from a pack if a
    Real-Estate / Furniture operator later reports "how did this
    field get here?".
    """
    field = await get_field(session, field_id)
    if field is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="custom field not found",
        )

    before = _snapshot(field)
    field_uuid = field.id
    await _da.delete_field_row(session, field)
    await session.commit()

    await log_entity_change(
        action="custom_fields.deleted",
        entity_type="custom_field_definition",
        entity_id=field_uuid,
        before=before,
    )
