"""Seed runner.

Two modes:

    python -m src.seeds.run             Unattended. What `deploy/deploy.sh` calls.
    python -m src.seeds.run <name>      One named seed, whatever its class.
    python -m src.seeds.run --list      Show every seed and its class.

The unattended mode names no seeds on purpose — `src/seeds/registry.py` decides
what is safe to run, so the rule lives beside the seeds instead of in a shell
script that has to be kept in sync with them.

Naming a seed explicitly always runs it. That is a human typing a specific
thing on a specific machine, which is exactly the case the classification is
protecting against automating.
"""

import asyncio
import os
import sys

from sqlalchemy import func, select

from src.app.core.tenants.models import Organization
from src.app.scripts.seed_demo_org import DEMO_ORG_ID
from src.app.shared.db import async_session
from src.seeds.registry import SEEDS, Seed, SeedClass, seed_by_name, seeds_in

# Groups kept so existing muscle memory and docs keep working.
GROUPS: dict[str, tuple[str, ...]] = {
    "demo": ("demo_org", "demo_admin_user", "contact_fields", "call_outcomes"),
    "layered": ("demo_org", "demo_admin_user", "contact_fields", "call_outcomes"),
    "countries": ("countries", "states"),
    # Pre-registry name for the legacy admin-panel accounts.
    "admin": ("super_admin",),
}

# MANUAL_ONLY seeds the unattended runner additionally runs when IS_DEVELOPMENT
# is true, so one `run.cmd seed` still gives a developer a usable database after
# the db volume is dropped.
#
# An explicit ALLOWLIST, not "every MANUAL_ONLY seed". The difference is not
# cosmetic: `core_demo_org` is correctly classified MANUAL_ONLY and is also
# currently broken (it asks for permission keys `pipelines.write`,
# `walk_ins.read` and `walk_ins.write`, which the module registry no longer
# publishes). Running every manual seed locally meant one stale demo script
# failed the whole seed run. Naming the set means adding a seed here is a
# decision rather than a side effect.
LOCAL_EXTRAS: tuple[str, ...] = (
    "super_admin",
    "demo_org",
    "demo_admin_user",
    "contact_fields",
    "call_outcomes",
    "dev_user",
)


async def _database_has_real_data() -> bool:
    """True when any organization other than the demo fixture exists.

    This is the FRESH_ONLY gate. It asks about DATA, not about the environment:
    production on day zero is genuinely fresh and should get everything, while a
    local database somebody has been working in for a week should not silently
    lose rows to a reconciling seed.
    """
    async with async_session() as session:
        count = await session.scalar(
            select(func.count()).select_from(Organization).where(Organization.id != DEMO_ORG_ID)
        )
    return bool(count)


async def _run(seed: Seed) -> None:
    await seed.run()


async def run_unattended() -> None:
    """Run everything the current machine and database make safe.

    Prints the verdict for every class, including the ones it skips. A deploy
    log that says nothing about seeds is indistinguishable from one where they
    silently did nothing.
    """
    is_development = os.getenv("IS_DEVELOPMENT", "false").lower() == "true"
    has_real_data = await _database_has_real_data()

    print(
        f"Seeds: IS_DEVELOPMENT={str(is_development).lower()}, "
        f"database {'holds real orgs' if has_real_data else 'is fresh'}."
    )

    for seed in seeds_in(SeedClass.EVERY_DEPLOY):
        await _run(seed)

    for seed in seeds_in(SeedClass.FRESH_ONLY):
        if has_real_data:
            print(f"  skip {seed.name} (fresh-only; this database holds real orgs)")
            continue
        await _run(seed)

    for seed in seeds_in(SeedClass.MANUAL_ONLY):
        if not is_development:
            print(f"  skip {seed.name} (manual-only; IS_DEVELOPMENT is not true)")
        elif seed.name not in LOCAL_EXTRAS:
            print(f"  skip {seed.name} (manual-only; not in LOCAL_EXTRAS)")
        else:
            await _run(seed)

    print("All seeds completed.")


async def run_named(name: str) -> None:
    if name in GROUPS:
        for member in GROUPS[name]:
            seed = seed_by_name(member)
            if seed is None:
                raise SystemExit(f"Group '{name}' references unknown seed '{member}'.")
            await _run(seed)
        return

    seed = seed_by_name(name)
    if seed is None:
        names = ", ".join(sorted([s.name for s in SEEDS] + list(GROUPS)))
        raise SystemExit(f"Unknown seed: {name}\nAvailable: {names}")
    await _run(seed)


def print_listing() -> None:
    width = max(len(s.name) for s in SEEDS)
    for seed_class in SeedClass:
        print(f"\n{seed_class.value}:")
        for seed in seeds_in(seed_class):
            print(f"  {seed.name.ljust(width)}  {seed.reason}")
    if GROUPS:
        print("\ngroups:")
        for group, members in GROUPS.items():
            print(f"  {group.ljust(width)}  {', '.join(members)}")


def main() -> None:
    args = sys.argv[1:]

    if not args:
        asyncio.run(run_unattended())
    elif args[0] in ("--list", "-l", "list"):
        print_listing()
    else:
        asyncio.run(run_named(args[0]))


if __name__ == "__main__":
    main()
