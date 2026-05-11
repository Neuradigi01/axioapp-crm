"""
Seed script — run manually after migrations.

Usage:
    python -m src.seeds.run          # Run all seeds
    python -m src.seeds.run admin    # Seed super admin only
    python -m src.seeds.run routes   # Seed default routes only
"""
import sys
import asyncio
from src.seeds.seed_admin import seed_super_admin
from src.seeds.seed_routes import seed_routes
from src.seeds.seed_countries import seed_countries, seed_states


async def run_all():
    await seed_super_admin()
    await seed_routes()
    await seed_countries()
    await seed_states()
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
