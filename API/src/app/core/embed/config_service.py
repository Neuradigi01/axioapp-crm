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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.embed.models import WidgetConfig
from src.app.core.embed.schemas import (
    WidgetConfigDocument,
    WidgetConfigField,
    WidgetConfigUpdate,
)
from src.app.shared.db import async_session


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


__all__ = ["get_or_create", "public_get", "update"]
