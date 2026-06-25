"""HTTP routes for roles + the global permission registry.

Five endpoints:

  GET    /api/v1/roles            list roles in the caller's org
  POST   /api/v1/roles            create a custom role
  PATCH  /api/v1/roles/{id}       rename / replace permission grants
  DELETE /api/v1/roles/{id}       delete a custom role
  GET    /api/v1/permissions      list the global permission registry

All write endpoints require `roles.write`. The two reads require
`roles.read`. System roles (those seeded by `pack.yaml` /
`seed_*.py`) are read-only — PATCH / DELETE returns 403.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException

from src.app.core.auth.dependencies import require_permissions
from src.app.core.permissions import role_templates
from src.app.core.permissions import service as permissions_service
from src.app.core.permissions.schemas import (
    PermissionOut,
    RoleCreate,
    RoleOut,
    RoleTemplateOut,
    RoleUpdate,
    RoleWithCounts,
)
from src.app.core.permissions.service import (
    create_role,
    delete_role,
    list_all_permissions,
    list_roles_in_org,
    update_role,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


roles_router = APIRouter(prefix="/roles", tags=["Roles"])
permissions_router = APIRouter(prefix="/permissions", tags=["Permissions"])
role_templates_router = APIRouter(prefix="/role-templates", tags=["Role Templates"])


# --- /roles --------------------------------------------------------------


@roles_router.get("", response_model=list[RoleWithCounts])
async def list_roles_endpoint(
    user: User = Depends(require_permissions("roles.read")),
    session: AsyncSession = Depends(get_db),
) -> list[RoleWithCounts]:
    rows = await list_roles_in_org(session, org_id=user.org_id)
    return [RoleWithCounts.model_validate(r) for r in rows]


@roles_router.post(
    "",
    response_model=RoleOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_role_endpoint(
    payload: RoleCreate,
    user: User = Depends(require_permissions("roles.write")),
    session: AsyncSession = Depends(get_db),
) -> RoleOut:
    role = await create_role(session, org_id=user.org_id, payload=payload)
    return RoleOut.model_validate(role)


@roles_router.patch("/{role_id}", response_model=RoleOut)
async def update_role_endpoint(
    role_id: uuid.UUID,
    payload: RoleUpdate,
    user: User = Depends(require_permissions("roles.write")),
    session: AsyncSession = Depends(get_db),
) -> RoleOut:
    role = await update_role(
        session, role_id=role_id, org_id=user.org_id, payload=payload
    )
    return RoleOut.model_validate(role)


@roles_router.delete(
    "/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_role_endpoint(
    role_id: uuid.UUID,
    user: User = Depends(require_permissions("roles.write")),
    session: AsyncSession = Depends(get_db),
) -> Response:
    await delete_role(session, role_id=role_id, org_id=user.org_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- /permissions --------------------------------------------------------


@permissions_router.get("", response_model=list[PermissionOut])
async def list_permissions_endpoint(
    _user: User = Depends(require_permissions("roles.read")),
    session: AsyncSession = Depends(get_db),
) -> list[PermissionOut]:
    rows = await list_all_permissions(session)
    return [PermissionOut.model_validate(p) for p in rows]


# --- /role-templates -----------------------------------------------------


@role_templates_router.get("", response_model=list[RoleTemplateOut])
async def list_role_templates_endpoint(
    user: User = Depends(require_permissions("roles.read")),
    session: AsyncSession = Depends(get_db),
) -> list[RoleTemplateOut]:
    installed = await role_templates.installed_template_names(session, user.org_id)
    out: list[RoleTemplateOut] = []
    for t in role_templates.ROLE_TEMPLATES.values():
        keys = (
            list(t.permission_keys) if isinstance(t.permission_keys, list) else []
        )
        out.append(
            RoleTemplateOut(
                key=t.key,
                name=t.name,
                description=t.description,
                is_system=t.is_system,
                is_owner=t.is_owner,
                auto_install_on_org_create=t.auto_install_on_org_create,
                permission_keys=keys,
                installed=t.name in installed,
            )
        )
    return out


@role_templates_router.post(
    "/{template_key}/install",
    response_model=RoleOut,
    status_code=status.HTTP_201_CREATED,
)
async def install_role_template_endpoint(
    template_key: str,
    user: User = Depends(require_permissions("roles.write")),
    session: AsyncSession = Depends(get_db),
) -> RoleOut:
    template = role_templates.ROLE_TEMPLATES.get(template_key)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown role template: {template_key!r}",
        )
    if template.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "the Owner template cannot be installed via this endpoint — "
                "Owner is assigned by the signup flow and there is exactly one "
                "Owner per org"
            ),
        )

    installed = await role_templates.installed_template_names(session, user.org_id)
    if template.name in installed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"role {template.name!r} already exists in this org",
        )

    role = await permissions_service.install_role_template(
        session, org_id=user.org_id, template_key=template_key
    )
    return RoleOut.model_validate(role)
