"""
Seed script — run manually after migrations.

Usage:
    python -m src.seeds.run            # Run all seeds (legacy + layered)
    python -m src.seeds.run admin      # Seed super admin only (legacy)
    python -m src.seeds.run routes     # Seed default routes only
    python -m src.seeds.run layered    # Seed FurnitureCRM demo org + admin role + user
"""

import asyncio
import sys

from src.app.scripts.seed_admin_user import seed_admin_user
from src.app.scripts.seed_call_outcomes import seed_call_outcomes
from src.app.scripts.seed_contact_system_fields import seed_contact_system_fields
from src.app.scripts.seed_demo_org import seed_demo_org
from src.seeds.seed_admin import seed_super_admin
from src.seeds.seed_countries import seed_countries, seed_states
from src.seeds.seed_routes import seed_routes


async def run_layered():
    """FurnitureCRM layered seeds: demo org → admin role + permissions + admin user → contact system fields → call outcomes."""
    await seed_demo_org()
    await seed_admin_user()
    await seed_contact_system_fields()
    await seed_call_outcomes()


async def run_contact_fields():
    await seed_contact_system_fields()


async def run_all():
    await seed_super_admin()
    await seed_routes()
    await seed_countries()
    await seed_states()
    await run_layered()
    print("All seeds completed.")


async def run_admin():
    await seed_super_admin()


async def run_routes():
    await seed_routes()


async def run_countries():
    await seed_countries()
    await seed_states()


SEED_MAP = {
    "admin": run_admin,
    "routes": run_routes,
    "countries": run_countries,
    "layered": run_layered,
    "contact_fields": run_contact_fields,
}


def main():
    args = sys.argv[1:]

    if not args:
        asyncio.run(run_all())
    elif args[0] in SEED_MAP:
        asyncio.run(SEED_MAP[args[0]]())
    else:
        print(f"Unknown seed: {args[0]}")
        print(f"Available: {', '.join(SEED_MAP.keys())}")
        sys.exit(1)


if __name__ == "__main__":
    main()
