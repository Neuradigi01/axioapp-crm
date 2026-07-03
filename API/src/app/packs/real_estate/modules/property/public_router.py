"""Public (unauthenticated) property endpoints.

Mounted at ``/api/public/*``. Two surfaces:

  * ``GET /api/public/properties?org={slug}`` — grid of every
    ``published`` property for the org identified by ``slug``.
  * ``GET /api/public/property/{token}`` — detail for the property
    whose Fernet token decodes to ``(property_id, org_id)`` and is
    currently ``published``.

Every non-happy path (invalid token, wrong org, non-published,
missing) resolves to the same **404 property not available** — no
side-channel that would leak the existence of a listing in a
different state.

The router intentionally does NOT depend on ``require_permissions``
or any auth artefact. It uses ``get_db`` for a session but does not
reach into the request context, so unauthenticated requests never
carry an ``org_id`` that could scope RLS the wrong way.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.tenants import data_access as tenants_da
from src.app.packs.real_estate.modules.property.schemas import (
    PublicPropertyCardOut,
    PublicPropertyDetailOut,
)
from src.app.packs.real_estate.modules.property.service import (
    get_public_property,
    list_public_properties,
)
from src.app.shared.db import get_db

router = APIRouter(prefix="/public", tags=["Public (Property)"])


@router.get(
    "/properties",
    response_model=list[PublicPropertyCardOut],
    include_in_schema=True,
)
async def list_public_properties_endpoint(
    org: str = Query(..., min_length=1, max_length=64, description="Organization slug"),
    db: AsyncSession = Depends(get_db),
) -> list[PublicPropertyCardOut]:
    """Public grid of every published property for one org.

    Lookup by ``slug`` because that's the URL-safe identifier the org
    controls; we deliberately never accept ``org_id`` UUIDs on public
    surfaces. Returns an empty list (not 404) if the slug doesn't
    resolve — the same shape a real but empty grid would return, so
    scrapers can't enumerate orgs by response code."""
    row = await tenants_da.get_organization_by_slug(db, org)
    if row is None:
        return []
    return await list_public_properties(db, org_id=row.id)


@router.get(
    "/property/{token}",
    response_model=PublicPropertyDetailOut,
    include_in_schema=True,
)
async def get_public_property_endpoint(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> PublicPropertyDetailOut:
    detail = await get_public_property(db, token=token)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="property not available",
        )
    return detail
