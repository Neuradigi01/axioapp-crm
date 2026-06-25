"""Per-org widget config — service layer.

Two write paths:

  - `get_or_create(session, org_id)` — used by both the admin GET
    and the public GET (via the embed key → org resolver). Lazily
    seeds the documented default config on first read so an Owner
    never sees "no config yet" — they always get a usable starting
    point they can edit.
  - `update(session, org_id, actor, payload)` — patch-style update.
    Each top-level field in `WidgetConfigUpdate` either replaces the
    existing value or, when None, leaves it alone. The merged
    document is re-validated through `WidgetConfigDocument` before
    persistence so the on-disk shape is always valid.

The `public_get(org_id)` helper opens its own session, bypasses the
tenant ORM filter (no context set on the public path), and queries
explicitly by `org_id` resolved from the embed key — equivalent
authorisation to RLS for read.

Audit: `embed.config.updated` on every successful PUT.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.shared.audit import log_entity_change
from src.app.core.custom_fields.models import (
    CustomFieldDefinition,
    FieldType,
)
from src.app.core.embed import data_access as _da
from src.app.core.embed.models import WidgetConfig
from src.app.core.embed.schemas import (
    AvailableCustomField,
    WidgetConfigDocument,
    WidgetConfigField,
    WidgetConfigUpdate,
)
from src.app.shared.db import async_session


# Contact custom-field types the widget can render. Limiting to a
# safe subset of the full `FieldType` enum so unsupported types
# (multiselect, datetime, boolean, currency) can't be opted in and
# then fail to render — Owner gets a clear "not supported" error
# instead of a broken form on customer sites.
_WIDGET_SUPPORTED_CUSTOM_TYPES: set[str] = {
    FieldType.text.value,
    FieldType.number.value,
    FieldType.select.value,
    FieldType.date.value,
    FieldType.phone.value,
    FieldType.email.value,
}


_WIDGET_ENTITIES: tuple[str, ...] = ("contact", "lead")


def _default_document() -> WidgetConfigDocument:
    """The shape every freshly-created org starts with."""
    return WidgetConfigDocument(
        fields=[
            WidgetConfigField(
                key="full_name",
                label="Your name",
                placeholder="Asha Reddy",
                required=True,
                order=0,
                field_type="text",
            ),
            WidgetConfigField(
                key="phone",
                label="Phone",
                placeholder="+91 …",
                required=True,
                order=1,
                field_type="tel",
            ),
            WidgetConfigField(
                key="email",
                label="Email",
                placeholder="you@…",
                required=False,
                order=2,
                field_type="email",
            ),
            WidgetConfigField(
                key="interest",
                label="Interested in",
                placeholder="Sofa, Bed, Wardrobe…",
                required=False,
                order=3,
                field_type="select",
                options=["Sofas", "Beds", "Dining", "Wardrobes", "Other"],
            ),
            WidgetConfigField(
                key="notes",
                label="Tell us more",
                placeholder="Anything we should know?",
                required=False,
                order=4,
                field_type="textarea",
            ),
        ],
        submit_button_label="Get a quote",
        thank_you_message="Thanks — we'll reach out shortly.",
        thank_you_url=None,
    )


async def get_or_create(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> WidgetConfig:
    """Return the org's widget config row, seeding defaults on miss."""
    existing = await _da.get_widget_config_for_org(session, org_id)
    if existing is not None:
        return existing

    row = WidgetConfig(
        org_id=org_id,
        config=_default_document().model_dump(mode="json"),
    )
    _da.insert_widget_config(session, row)
    await session.commit()
    await session.refresh(row)
    return row


async def update(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: Optional[uuid.UUID],
    payload: WidgetConfigUpdate,
) -> WidgetConfig:
    """Patch-style update. Re-validates the merged document so we
    never persist an invalid shape. Emits `embed.config.updated`."""
    row = await get_or_create(session, org_id=org_id)
    current = WidgetConfigDocument.model_validate(row.config)

    patch = payload.model_dump(exclude_unset=True, exclude_none=False)
    merged_dict = current.model_dump(mode="json")
    for key, value in patch.items():
        merged_dict[key] = value
    merged = WidgetConfigDocument.model_validate(merged_dict)

    await _validate_custom_field_refs(session, fields=merged.fields)

    row.config = merged.model_dump(mode="json")
    row.updated_by = actor_id
    await session.commit()
    await session.refresh(row)

    await log_entity_change(
        action="embed.config.updated",
        entity_type="widget_config",
        entity_id=row.id,
        after={
            "config_id": str(row.id),
            "fields": [f.key for f in merged.fields],
            "submit_button_label": merged.submit_button_label,
        },
    )
    return row


async def _validate_custom_field_refs(
    session: AsyncSession,
    *,
    fields: list[WidgetConfigField],
) -> None:
    """Reject the PUT if a custom-source field references an unknown
    custom field, the wrong entity, or a type the widget bundle
    doesn't know how to render."""
    custom_refs = [f for f in fields if f.field_source == "custom"]
    if not custom_refs:
        return

    needed: set[tuple[str, str]] = {(f.entity, f.key) for f in custom_refs}
    rows = await _da.list_custom_field_defs_by_keys(
        session,
        entity_types=_WIDGET_ENTITIES,
        field_keys=[k for _, k in needed],
    )
    found_by_pair: dict[tuple[str, str], CustomFieldDefinition] = {
        (r.entity_type, r.field_key): r for r in rows
    }

    missing = [
        f"{entity}.{key}"
        for entity, key in sorted(needed)
        if (entity, key) not in found_by_pair
    ]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Custom field(s) {missing} are not defined — add them "
                "under Settings → Custom fields first (pick the right "
                "Entity dropdown), then opt them in to the widget."
            ),
        )

    unsupported = [
        f"{entity}.{key} ({found_by_pair[(entity, key)].field_type.value})"
        for entity, key in sorted(needed)
        if found_by_pair[(entity, key)].field_type.value
        not in _WIDGET_SUPPORTED_CUSTOM_TYPES
    ]
    if unsupported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Custom field type not supported on the widget: "
                f"{', '.join(unsupported)}. "
                f"Supported: {sorted(_WIDGET_SUPPORTED_CUSTOM_TYPES)}."
            ),
        )


async def list_available_widget_custom_fields(
    session: AsyncSession,
) -> list[AvailableCustomField]:
    """Read-only listing of custom fields (contact OR lead) the Settings
    picker can offer for widget opt-in."""
    rows = await _da.list_custom_fields_for_widget_entities(
        session, entity_types=_WIDGET_ENTITIES
    )
    out: list[AvailableCustomField] = []
    for row in rows:
        opts: Optional[list[str]] = None
        if isinstance(row.options, dict):
            raw = row.options.get("choices") or row.options.get("options")
            if isinstance(raw, list):
                opts = [str(v) for v in raw]
        elif isinstance(row.options, list):
            opts = [str(v) for v in row.options]
        out.append(
            AvailableCustomField(
                entity=row.entity_type,
                field_key=row.field_key,
                field_label=row.field_label,
                field_type=row.field_type.value,
                is_required=row.is_required,
                options=opts,
                widget_supported=(
                    row.field_type.value in _WIDGET_SUPPORTED_CUSTOM_TYPES
                ),
            )
        )
    return out


# Back-compat alias — the old function name still works in case anything
# external imports it. Drop in a follow-on cleanup.
list_available_contact_custom_fields = list_available_widget_custom_fields


async def public_get(org_id: uuid.UUID) -> Optional[WidgetConfig]:
    """Public-endpoint read. Opens its own session WITHOUT setting
    tenant context — the explicit query keyed by ``org_id`` (resolved
    from the embed key) is the authorisation gate."""
    async with async_session() as session:
        return await _da.get_widget_config_for_org(session, org_id)


__all__ = [
    "get_or_create",
    "list_available_contact_custom_fields",
    "list_available_widget_custom_fields",
    "public_get",
    "update",
]
