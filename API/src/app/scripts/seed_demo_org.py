"""Seed one demo organization. Idempotent — safe to re-run.

Usage (from inside the api/ directory or container):
    python -m src.app.scripts.seed_demo_org
"""
import asyncio
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.app.shared.db import async_session
from src.app.core.tenants.models import Organization

DEMO_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEMO_ORG = {
    "id": DEMO_ORG_ID,
    "name": "Demo Furniture Store",
    "slug": "demo",
    "pack_id": "furniture",
    "pack_version": None,
    "currency": "INR",
    "tax_rate": Decimal("18.00"),
    "timezone": "Asia/Kolkata",
}


async def seed_demo_org() -> None:
    async with async_session() as session:
        existing = (
            await session.execute(select(Organization).where(Organization.id == DEMO_ORG_ID))
        ).scalar_one_or_none()
        if existing is not None:
            print(f"Demo org already exists (id={existing.id}, slug={existing.slug}). Skipped.")
            return

        stmt = insert(Organization).values(**DEMO_ORG).on_conflict_do_nothing(index_elements=["id"])
        await session.execute(stmt)
        await session.commit()
        print(f"Demo org seeded: id={DEMO_ORG_ID}, slug={DEMO_ORG['slug']}")


if __name__ == "__main__":
    asyncio.run(seed_demo_org())
