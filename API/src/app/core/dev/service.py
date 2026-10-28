"""Service layer for the dev module.

Wraps the dev DAL and shapes the raw rows into the `DemoLogin` response
schema. No business logic — dev tooling is internal-only, mounted only
when `IS_DEVELOPMENT=true`.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.dev import data_access
from src.app.core.dev.schemas import DemoLogin


async def list_demo_logins(session: AsyncSession) -> list[DemoLogin]:
    """Return every demo login as a `DemoLogin` list, label-derived
    where the DB row is missing an explicit label."""
    rows = await data_access.list_demo_login_rows(session)
    out: list[DemoLogin] = []
    for r in rows:
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
