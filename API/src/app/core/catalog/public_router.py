"""Public (unauthenticated) catalog endpoints.

Mounted at ``/api/public/*``. Two surfaces:

  * ``GET /api/public/catalog?org={slug}`` — grid of every
    ``published`` catalog item for the org identified by ``slug``.
  * ``GET /api/public/catalog/{token}`` — detail for the item whose
    Fernet token decodes to ``(item_id, org_id)`` and is currently
    ``published``.

Every non-happy path (invalid token, wrong org, non-published,
missing) resolves to the same **404 product not available** — no
side-channel that would leak the existence of an item in a
different state.

The router intentionally does NOT depend on ``require_permissions``
or any auth artefact. It uses ``get_db`` for a session but does not
reach into the request context, so unauthenticated requests never
carry an ``org_id`` that could scope the ORM tenant filter the wrong way.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.catalog.schemas import (
    PublicCatalogCardOut,
    PublicCatalogDetailOut,
    PublicStoreOut,
)
from src.app.core.catalog.service import (
    get_public_item,
    get_public_store,
    list_public_items,
)
from src.app.core.tenants import data_access as tenants_da
from src.app.shared.db import get_db

router = APIRouter(prefix="/public", tags=["Public (Catalog)"])


@router.get(
    "/catalog",
    response_model=list[PublicCatalogCardOut],
    include_in_schema=True,
)
async def list_public_catalog_endpoint(
    org: str = Query(..., min_length=1, max_length=64, description="Organization slug"),
    db: AsyncSession = Depends(get_db),
) -> list[PublicCatalogCardOut]:
    """Public grid of every published product for one org.

    Lookup by ``slug`` because that's the URL-safe identifier the org
    controls; we deliberately never accept ``org_id`` UUIDs on public
    surfaces. Returns an empty list (not 404) when the slug doesn't
    resolve — same shape a real but empty grid would return, so
    scrapers can't enumerate orgs by response code."""
    row = await tenants_da.get_organization_by_slug(db, org)
    if row is None:
        return []
    return await list_public_items(db, org_id=row.id)


@router.get(
    "/catalog/{token}",
    response_model=PublicCatalogDetailOut,
    include_in_schema=True,
)
async def get_public_catalog_item_endpoint(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> PublicCatalogDetailOut:
    detail = await get_public_item(db, token=token)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="product not available",
        )
    return detail


@router.get(
    "/store/{token}",
    response_model=PublicStoreOut,
    include_in_schema=True,
)
async def get_public_store_endpoint(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> PublicStoreOut:
    """Public storefront view — decrypts the Fernet store token to an
    org id and returns the org's display name plus every currently-
    published catalog item. 404 on every failure mode (bad token,
    wrong key, tampered, per-item token fed here, unknown org) — no
    side channel."""
    detail = await get_public_store(db, token=token)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="store not available",
        )
    return detail
