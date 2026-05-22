"""Service layer for `import_presets`.

Three operations:

  - `list(source_platform)` — returns system + org-owned presets for
    a platform. Service explicitly OR's the predicate because the
    `ImportPreset` model is NOT `TenantScoped` (system rows have
    `org_id IS NULL`). PG-level RLS backs this up.
  - `create(...)` — saves an org-owned preset. Validates the mapping
    targets against the shared `targets.list_target_keys()` set (same
    whitelist Step 2's `commit_mapping` enforces — they cannot drift).
  - `delete(preset_id)` — removes an org-owned preset. System presets
    return 403 (they're shipped via the seed migration and never
    mutated by the app).

Auto-naming: when `create` is called with no `name`, the service
picks `"<platform> v<N>"` where N is `1 + the highest existing
"<platform> vK" name in this org for this platform`. Lets clients
hit "Save preset" multiple times without naming each one.
"""
from __future__ import annotations

import re
import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.leads.imports.models import ImportPreset
from src.app.core.leads.imports.schemas import SourcePlatform
from src.app.core.leads.imports.targets import list_target_keys


_VERSION_NAME_RE = re.compile(r"^(?P<platform>[a-z_]+) v(?P<num>\d+)$")


async def list_presets(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    source_platform: SourcePlatform,
) -> list[ImportPreset]:
    """Return system + this-org presets for the given platform.

    System rows first (newest first), then org-owned rows (newest first).
    Frontend uses the order to decide which to default-select: the
    org's most recent preset wins; system fallback if none.
    """
    stmt = (
        select(ImportPreset)
        .where(ImportPreset.source_platform == source_platform)
        .where(
            or_(
                ImportPreset.is_system.is_(True),
                ImportPreset.org_id == org_id,
            )
        )
        .order_by(
            ImportPreset.is_system.desc(),
            ImportPreset.created_at.desc(),
        )
    )
    return list((await session.execute(stmt)).scalars().all())


async def create_preset(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    name: Optional[str],
    source_platform: SourcePlatform,
    mapping: dict[str, Optional[str]],
) -> ImportPreset:
    """Validate the mapping + persist an org-owned preset.

    Raises 422 if any non-null mapping value is not a known target.
    Raises 409 if `name` is supplied and collides with an existing
    name in this (org, platform) pair.
    """
    allowed = await list_target_keys(session)
    bad = [v for v in mapping.values() if v and v not in allowed]
    if bad:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Mapping references unknown or forbidden targets: "
                f"{sorted(set(bad))}. Hit GET /leads/import/targets for "
                "the canonical list of allowed target keys."
            ),
        )

    final_name = (name or "").strip() or await _next_auto_name(
        session, org_id=org_id, source_platform=source_platform
    )

    row = ImportPreset(
        org_id=org_id,
        source_platform=source_platform,
        name=final_name,
        mapping=mapping,
        is_system=False,
        created_by=actor_id,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A preset named {final_name!r} already exists for "
                f"platform '{source_platform}' in this org."
            ),
        ) from exc
    await session.refresh(row)

    await audit.log(
        "import_presets.created",
        entity_type="import_preset",
        entity_id=row.id,
        after={
            "preset_id": str(row.id),
            "source_platform": row.source_platform,
            "name": row.name,
            "mapping_keys": sorted(mapping.keys()),
        },
    )
    return row


async def delete_preset(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID,
    preset_id: uuid.UUID,
) -> None:
    """Remove an org-owned preset. 403 on system presets; 404 if missing.

    The RLS write policy already blocks system-preset deletes at the
    PG level. We raise an explicit 403 in the service so the error
    message is helpful — the bare RLS rejection surfaces as a row-not-
    found in some drivers.
    """
    row = (
        await session.execute(
            select(ImportPreset).where(ImportPreset.id == preset_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="preset not found"
        )
    if row.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="system presets cannot be deleted",
        )
    if row.org_id != org_id:
        # Defence-in-depth — RLS already shouldn't show this row to
        # other orgs, but in case it slipped through.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="preset not found"
        )

    preset_id_snapshot = row.id
    preset_name_snapshot = row.name
    preset_platform_snapshot = row.source_platform

    await session.delete(row)
    await session.commit()

    await audit.log(
        "import_presets.deleted",
        entity_type="import_preset",
        entity_id=preset_id_snapshot,
        before={
            "preset_id": str(preset_id_snapshot),
            "source_platform": preset_platform_snapshot,
            "name": preset_name_snapshot,
        },
    )


async def _next_auto_name(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    source_platform: SourcePlatform,
) -> str:
    """Pick the next `"<platform> vN"` name for org-owned presets."""
    stmt = (
        select(ImportPreset.name)
        .where(ImportPreset.org_id == org_id)
        .where(ImportPreset.source_platform == source_platform)
    )
    existing = {n for (n,) in (await session.execute(stmt)).all()}
    next_num = 1
    for name in existing:
        m = _VERSION_NAME_RE.match(name)
        if m and m.group("platform") == source_platform:
            num = int(m.group("num"))
            if num >= next_num:
                next_num = num + 1
    return f"{source_platform} v{next_num}"


__all__ = ["create_preset", "delete_preset", "list_presets"]
