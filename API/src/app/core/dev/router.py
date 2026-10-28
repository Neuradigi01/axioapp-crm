"""Dev-only HTTP routes.

  GET /api/v1/_dev/demo-logins
    Returns a flat list of seeded test logins for the login page's
    "Test logins" dropdown.

Mounted in `main.py` ONLY when `IS_DEVELOPMENT=true`. Production
builds don't mount this router at all; `/api/v1/_dev/demo-logins`
404s there, and the login page's dropdown auto-hides on empty
response.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.dev.schemas import DemoLogin
from src.app.core.dev.service import list_demo_logins
from src.app.shared.db import get_db

router = APIRouter(prefix="/_dev", tags=["Dev"])


@router.get("/demo-logins", response_model=list[DemoLogin])
async def list_demo_logins_endpoint(
    db: AsyncSession = Depends(get_db),
) -> list[DemoLogin]:
    """List every demo login the seed scripts created. Read-only.

    Ordered so Core CRM entries come first, then Furniture — matches
    what most reviewers expect to click through.
    """
    return await list_demo_logins(db)
