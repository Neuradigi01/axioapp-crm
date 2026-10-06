"""Reusable FastAPI dependencies for vertical-pack gating.

`require_pack(pack_id)` keeps a pack's HTTP surface invisible to orgs
that are not on that pack. Permission keys alone are not enough — a
stray grant (role templates, manual role edits) would otherwise expose
furniture endpoints to a real-estate org. The composition root
(`main.py`) attaches it to every pack router, so core stays unaware of
which packs exist.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.tenants.service import get_organization_by_id
from src.app.shared.context import get_context
from src.app.shared.db import get_db


def require_pack(pack_id: str):
    """Return a dependency that 404s unless the caller's org is on `pack_id`.

    404 (not 403) because the feature does not exist for other packs —
    there is nothing the caller could be granted to reach it.
    """

    async def _check(db: AsyncSession = Depends(get_db)) -> None:
        org_id = get_context().org_id
        org = await get_organization_by_id(db, org_id) if org_id is not None else None
        if org is None or org.template_id != pack_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="This feature is not available for your workspace.",
            )

    return _check
