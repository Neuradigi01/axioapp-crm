"""Backfill `settings.integrations.manage` for existing Owner / Admin roles.

The ad-integrations module registers the `settings.integrations.manage`
permission key at startup, but earlier role-template snapshots did not
grant it to anyone. Orgs created before the template was patched have
Owner/Admin role rows with the grant missing — the Integrations tab in
Settings is hidden for them.

This script idempotently inserts the missing grants. Safe to re-run.

Usage (from `API/`):
    uv run python -m src.app.scripts.backfill_integrations_permission
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.permissions.models import Permission, Role, RolePermission
from src.app.shared.db import async_session

_KEY = "settings.integrations.manage"
_ROLE_NAMES = ("Owner", "Admin")


async def main() -> None:
    async with async_session() as session:
        perm = (
            await session.execute(select(Permission).where(Permission.key == _KEY))
        ).scalar_one_or_none()
        if perm is None:
            print(
                f"ERROR: permission '{_KEY}' is not in the catalog. "
                "Start the API at least once so the module-registry "
                "startup hook seeds it, then re-run."
            )
            return

        role_rows = (
            await session.execute(
                select(Role.id, Role.org_id, Role.name).where(Role.name.in_(_ROLE_NAMES))
            )
        ).all()
        if not role_rows:
            print("No Owner/Admin roles found — nothing to backfill.")
            return

        values = [{"role_id": r.id, "permission_id": perm.id} for r in role_rows]
        result = await session.execute(
            pg_insert(RolePermission)
            .values(values)
            .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
        )
        await session.commit()
        inserted = result.rowcount if result.rowcount is not None else 0
        print(
            f"Backfill complete: {len(role_rows)} role(s) considered, "
            f"{inserted} new grant(s) inserted."
        )
        for r in role_rows:
            print(f"  - role {r.name} (org {r.org_id})")


if __name__ == "__main__":
    asyncio.run(main())
