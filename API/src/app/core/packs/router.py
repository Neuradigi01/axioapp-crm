"""Pack catalog HTTP endpoint.

Serves the onboarding picker on `GET /api/v1/packs/catalog`. The
catalog is public (no auth required) and identical for all callers —
the response contains no PII and no org-scoped data. The onboarding
page fetches it on init to render the template tiles.
"""
from __future__ import annotations

from fastapi import APIRouter

from src.app.core.packs.schemas import CatalogResponse
from src.app.core.packs.service import get_catalog

router = APIRouter(prefix="/packs", tags=["packs"])


@router.get("/catalog", response_model=CatalogResponse)
async def list_catalog() -> CatalogResponse:
    return get_catalog()


__all__ = ["router"]
