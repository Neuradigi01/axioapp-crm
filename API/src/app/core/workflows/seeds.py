"""Placeholder for Step 20 — default workflow seeds per org.

Step 20 (``tasks/workflows/step-20-seeded-workflows-and-sequences-
absorption.md``) materialises the 15 gallery templates into real
``tbl_workflows`` rows for every new org, so a fresh signup has a
populated workflow library out of the box (mirrors the templates-
library seed-on-org-create flow).

Step 16 ships only the gallery / clone-from-gallery surface; this
module exists so the import paths Step 20 will reference are stable
ahead of time. ``seed_default_workflows`` is a no-op for now — Step
20 fills it in.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession


async def seed_default_workflows(
    session: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID | None
) -> int:
    """Seed the org with the 15 default workflows. Step 20 will fill
    this in by iterating over :data:`templates_gallery.CATALOG` and
    calling ``clone_from_gallery`` for each entry.

    Returns the number of workflows seeded — currently always 0
    because the body is deferred. Callers should be tolerant of the
    return value while Step 20 is in flight.
    """
    return 0


__all__ = ["seed_default_workflows"]
