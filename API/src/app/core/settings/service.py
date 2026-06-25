"""Service layer for OrgSettings.

`get_or_create` ensures every org has a row on first access — no
separate per-org seeding required. The pack installer (4.2) will
still call `patch_settings` to overwrite the generic defaults with
furniture-specific values once a pack is installed.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.settings.models import OrgSettings
from src.app.core.settings.schemas import (
    LeadRoutingConfigUpdate,
    OrgSettingsPatch,
)


async def get_or_create(
    session: AsyncSession, *, org_id: uuid.UUID
) -> OrgSettings:
    """Return the single settings row for `org_id`, creating it on
    first call. The defaults baked into the model (server_default) +
    the migration cover every column."""
    existing = (
        await session.execute(
            select(OrgSettings).where(OrgSettings.org_id == org_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = OrgSettings(org_id=org_id)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def patch_settings(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: OrgSettingsPatch,
) -> OrgSettings:
    """Apply only the explicitly-set keys; ignore everything else.

    `model_dump(exclude_unset=True)` is the strict-key filter — anything
    the client didn't send stays untouched. Combined with the schema's
    `extra='ignore'`, this means an attacker can't set `org_id` or any
    column we didn't whitelist.
    """
    row = await get_or_create(session, org_id=org_id)
    before = _snapshot(row)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return row
    for key, value in updates.items():
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    await audit.log(
        "settings.patched",
        entity_type="org_settings",
        entity_id=row.id,
        before=before,
        after=_snapshot(row),
    )
    return row


async def set_lead_routing_config(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: LeadRoutingConfigUpdate,
) -> dict[str, Any]:
    """Replace the org's lead-routing config and return the persisted
    dict.

    Owns the transaction so callers (leads router) don't.
    """
    row = await get_or_create(session, org_id=org_id)
    row.lead_routing_config = payload.model_dump()
    await session.commit()
    await session.refresh(row)
    return row.lead_routing_config


def _snapshot(row: OrgSettings) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "store_name": row.store_name,
        "currency": row.currency,
        "tax_rate": str(row.tax_rate),
        "timezone": row.timezone,
        "ai_enabled": row.ai_enabled,
        "reviews_auto_request_enabled": row.reviews_auto_request_enabled,
    }


__all__ = ["get_or_create", "patch_settings", "set_lead_routing_config"]
