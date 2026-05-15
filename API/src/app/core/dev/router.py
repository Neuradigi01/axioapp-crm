"""Dev-only HTTP routes.

  GET /api/v1/_dev/demo-logins
    Returns a flat list of seeded test logins for the login page's
    "Test logins" dropdown. Joins `users` (where `is_demo=True`),
    `demo_credentials`, and `organizations` so the frontend can fill
    the login form in one click.

Mounted in `main.py` ONLY when `IS_DEVELOPMENT=true`. Production
builds don't mount this router at all; `/api/v1/_dev/demo-logins`
404s there, and the login page's dropdown auto-hides on empty
response.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from src.app.core.dev.models import DemoCredential
from src.app.core.tenants.models import Organization
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/_dev", tags=["Dev"])


class DemoLogin(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label: str
    identifier: str
    password: str
    org_slug: str
    org_name: str


@router.get("/demo-logins", response_model=list[DemoLogin])
async def list_demo_logins(
    db: AsyncSession = Depends(get_db),
) -> list[DemoLogin]:
    """List every demo login the seed scripts created. Read-only.

    Ordered so Core CRM entries come first, then Furniture — matches
    what most reviewers expect to click through.
    """
    stmt = (
        select(
            User.email.label("identifier"),
            DemoCredential.plain_password.label("password"),
            DemoCredential.label.label("label_db"),
            Organization.slug.label("org_slug"),
            Organization.name.label("org_name"),
            Organization.pack_id.label("pack_id"),
        )
        # After DR.6.3 `User.id` is the bigint storage PK of
        # `tbl_user_login`. The UUID `DemoCredential.user_id` matches
        # the value preserved in `User.legacy_uuid` by the 0032 data
        # migration, so we join through that column instead.
        .join(DemoCredential, DemoCredential.user_id == User.legacy_uuid)
        .join(Organization, Organization.id == User.org_id)
        .where(User.is_demo.is_(True))
        # 'core' pack first, then 'furniture', then anything else.
        .order_by(Organization.pack_id.asc(), User.full_name.asc())
    )
    rows = (await db.execute(stmt)).all()

    out: list[DemoLogin] = []
    for r in rows:
        # Prefer the explicit label from the DB; fall back to a
        # derived "<Org name> — <user identifier>" if missing.
        label = r.label_db or _derive_label(r.org_name, r.identifier)
        out.append(
            DemoLogin(
                label=label,
                identifier=r.identifier,
                password=r.password,
                org_slug=r.org_slug,
                org_name=r.org_name,
            )
        )
    return out


def _derive_label(org_name: str, identifier: str) -> str:
    """Fallback when the seed didn't supply an explicit label."""
    return f"{org_name} — {identifier}"
