"""Module-registry HTTP surface.

  GET  /api/v1/modules          — list registered modules filtered by
                                  the calling user's permissions.
  POST /api/v1/dev/refresh-modules — dev-only hot reload (re-runs
                                  discovery without restarting the
                                  process). Gated by `IS_DEVELOPMENT`.

The list endpoint relies on `permissions.list_permissions_for_role`
to compute which `MODULE.permissions` keys the user holds, then asks
the registry to filter on that set.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from config import IS_DEVELOPMENT
from src.app.core.auth.dependencies import get_current_user
from src.app.core.module_registry import (
    ModuleDescriptor,
    discover_modules,
    registry,
)
from src.app.core.permissions.service import (
    list_permissions_for_role,
    register_permissions,
)
from src.app.core.tenants.service import get_organization_by_id
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(tags=["Modules"])


class ModuleOut(BaseModel):
    id: str
    name: str
    icon: str
    layer: str
    route: str
    frontend_route: str
    permissions: list[str]
    menu_position: int | None
    parent: str | None

    @classmethod
    def from_descriptor(cls, m: ModuleDescriptor) -> ModuleOut:
        return cls(**asdict(m))


class RefreshModulesResponse(BaseModel):
    discovered: list[str]


@router.get("/modules", response_model=list[ModuleOut])
async def list_modules(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ModuleOut]:
    granted = {p.key for p in await list_permissions_for_role(db, user.role_id)}
    org = await get_organization_by_id(db, user.org_id)
    org_template_id = org.template_id if org is not None else None
    return [
        ModuleOut.from_descriptor(m)
        for m in registry.list_for_user(granted, org_template_id=org_template_id)
    ]


@router.post("/dev/refresh-modules", response_model=RefreshModulesResponse)
async def refresh_modules(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> RefreshModulesResponse:
    if not IS_DEVELOPMENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dev-only endpoint",
        )

    registry.clear()
    discover_modules()

    all_permission_keys: list[str] = []
    for module in registry.list():
        all_permission_keys.extend(module.permissions)
    if all_permission_keys:
        await register_permissions(db, all_permission_keys)

    return RefreshModulesResponse(discovered=[m.id for m in registry.list()])
