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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.custom_fields.models import (
    CustomFieldDefinition,
    FieldType,
)
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


def _default_document() -> WidgetConfigDocument:
    """The shape every freshly-created org starts with. Mirrors the
    default in the Step 3 spec exactly so the UI never has to choose
    "what should this look like for a new tenant?"."""
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
    existing = (
        await session.execute(
            select(WidgetConfig).where(WidgetConfig.org_id == org_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    row = WidgetConfig(
        org_id=org_id,
        config=_default_document().model_dump(mode="json"),
    )
    session.add(row)
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
    # Pydantic patch-style: only top-level fields actually supplied
    # get merged. None values that WERE supplied still pass through
    # (e.g. clearing thank_you_url to None).
    merged_dict = current.model_dump(mode="json")
    for key, value in patch.items():
        merged_dict[key] = value
    merged = WidgetConfigDocument.model_validate(merged_dict)

    # Cross-table validation — any field with `field_source='custom'`
    # must reference a defined contact custom field whose type the
    # widget can render. Done here (not in WidgetConfigField's own
    # validator) because the validator is org-agnostic.
    await _validate_custom_field_refs(session, fields=merged.fields)

    row.config = merged.model_dump(mode="json")
    row.updated_by = actor_id
    await session.commit()
    await session.refresh(row)

    await audit.log(
        "embed.config.updated",
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
    custom field, a non-contact entity, or a type the widget bundle
    doesn't know how to render. Catches Owner typos + prevents
    exposing pack-defined system fields the renderer can't handle.
    """
    custom_refs = [f for f in fields if f.field_source == "custom"]
    if not custom_refs:
        return

    keys = sorted({f.key for f in custom_refs})
    rows = (
        (
            await session.execute(
                select(CustomFieldDefinition).where(
                    CustomFieldDefinition.entity_type == "contact",
                    CustomFieldDefinition.field_key.in_(keys),
                )
            )
        )
        .scalars()
        .all()
    )
    found_by_key = {r.field_key: r for r in rows}

    missing = [k for k in keys if k not in found_by_key]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Custom field(s) {missing} are not defined on the "
                "contact entity — add them under Settings → Custom "
                "fields first, then opt them in to the widget."
            ),
        )

    unsupported = [
        (k, found_by_key[k].field_type.value)
        for k in keys
        if found_by_key[k].field_type.value
        not in _WIDGET_SUPPORTED_CUSTOM_TYPES
    ]
    if unsupported:
        labels = ", ".join(f"{k} ({t})" for k, t in unsupported)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Custom field type not supported on the widget: {labels}. "
                f"Supported: {sorted(_WIDGET_SUPPORTED_CUSTOM_TYPES)}."
            ),
        )


async def list_available_contact_custom_fields(
    session: AsyncSession,
) -> list[AvailableCustomField]:
    """Read-only listing of contact custom fields the Settings picker
    can offer for widget opt-in. Includes a `widget_supported` flag —
    unsupported types stay in the list (so the Owner can see the
    field exists) but the picker greys them out.
    """
    rows = (
        (
            await session.execute(
                select(CustomFieldDefinition)
                .where(CustomFieldDefinition.entity_type == "contact")
                .where(CustomFieldDefinition.is_hidden.is_(False))
                .order_by(CustomFieldDefinition.display_order)
            )
        )
        .scalars()
        .all()
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


async def public_get(org_id: uuid.UUID) -> Optional[WidgetConfig]:
    """Public-endpoint read. Opens its own session WITHOUT setting
    tenant context — the explicit `WHERE org_id = ...` query is the
    authorisation gate. The embed key the caller proved knowledge
    of supplies the org_id.

    Returns None if the org has no config yet — public handler
    treats that as "use bundle defaults" so a freshly-created org
    with a freshly-issued key has a working widget out of the box.
    """
    async with async_session() as session:
        row = (
            await session.execute(
                select(WidgetConfig).where(WidgetConfig.org_id == org_id)
            )
        ).scalar_one_or_none()
        return row


__all__ = [
    "get_or_create",
    "list_available_contact_custom_fields",
    "public_get",
    "update",
]
