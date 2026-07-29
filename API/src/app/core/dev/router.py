"""Dev-only HTTP routes.

  GET /api/v1/_dev/demo-logins
    Returns a flat list of seeded test logins for the login page's
    "Test logins" dropdown.

Mounted in `main.py` ONLY when `IS_DEVELOPMENT=true`. Production
builds don't mount this router at all; `/api/v1/_dev/demo-logins`
404s there, and the login page's dropdown auto-hides on empty
response.

**Defense in depth:** every route is *also* gated at request time by
:func:`_require_dev_mode`. The startup env check in ``main.py`` is a
single-point-of-failure — flipping ``IS_DEVELOPMENT=true`` in prod for
one restart leaves the router mounted for the process lifetime, and
plaintext demo passwords ship to any authenticated caller. The
per-request guard re-reads the env for every hit so an operator can
clear the flag and cut off access immediately without a redeploy.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.dev.schemas import DemoLogin
from src.app.core.dev.service import list_demo_logins
from src.app.shared.db import get_db


def _require_dev_mode() -> None:
    """Per-request guard: re-check ``IS_DEVELOPMENT`` on every hit.

    The router itself is mount-gated in ``main.py``, but the mount is
    latched at process start. If ops turn the flag off (or discover
    it was on by mistake), this dependency shuts the endpoint off on
    the very next request without waiting for a restart. Returns
    404 — not 403 — to keep the surface indistinguishable from a
    production instance that never mounted the router at all.
    """
    if os.getenv("IS_DEVELOPMENT", "").lower() != "true":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


router = APIRouter(
    prefix="/_dev",
    tags=["Dev"],
    dependencies=[Depends(_require_dev_mode)],
)


@router.get("/demo-logins", response_model=list[DemoLogin])
async def list_demo_logins_endpoint(
    db: AsyncSession = Depends(get_db),
) -> list[DemoLogin]:
    """List every demo login the seed scripts created. Read-only.

    Ordered so Core CRM entries come first, then Furniture — matches
    what most reviewers expect to click through.
    """
    return await list_demo_logins(db)
