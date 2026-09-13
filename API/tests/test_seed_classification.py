"""Pin-test: every seed on disk is classified, and nothing dangerous is
classified as safe to run unattended.

`deploy/deploy.sh` runs `run.sh seed` on every deploy without naming any seed —
`src/seeds/registry.py` decides what actually executes. That makes the registry
a production safety boundary, not bookkeeping: a seed that is missing from it
is simply never run (silently), and a demo fixture wrongly marked
`EVERY_DEPLOY` puts known credentials on a live server.

These tests are pure — no database, no fixtures. They read the registry and the
source tree.
"""

from __future__ import annotations

import ast
import pathlib

from src.seeds.registry import SEEDS, SeedClass
from src.seeds.run import LOCAL_EXTRAS

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"

# Directories that hold seed entry points. Anything matching `async def seed_*`
# in these files is expected to be classified.
_SEED_SOURCES = (
    _SRC / "seeds",
    _SRC / "app" / "scripts",
)

# `async def seed_*` functions that are deliberately NOT registry entry points.
# Each one needs a reason, because the default answer is "register it".
_NOT_ENTRY_POINTS: dict[str, str] = {}


def _seed_functions_on_disk() -> dict[str, pathlib.Path]:
    """Every top-level `async def seed_*` under the seed source directories.

    Parsed rather than imported: importing every seed module to introspect it
    would execute module-level code and pull in the database layer, which this
    test deliberately does not depend on.
    """
    found: dict[str, pathlib.Path] = {}
    for directory in _SEED_SOURCES:
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("__"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("seed_"):
                    found[node.name] = path
    return found


def test_every_seed_on_disk_is_classified() -> None:
    """A new seed file must be added to the registry, or it never runs.

    This is the failure the registry exists to prevent: `seed_core_demo_org`
    sat unreferenced by any runner until the registry was introduced, so
    nothing called it and nothing said so.
    """
    registered = {seed.run.__name__ for seed in SEEDS}
    on_disk = _seed_functions_on_disk()

    unclassified = sorted(
        name for name in on_disk if name not in registered and name not in _NOT_ENTRY_POINTS
    )

    assert not unclassified, (
        "These seed functions are not in src/seeds/registry.py, so the runner "
        "will never execute them:\n"
        + "\n".join(f"  {name}  ({on_disk[name]})" for name in unclassified)
        + "\n\nAdd each to SEEDS with a class and a reason, or record it in "
        "_NOT_ENTRY_POINTS with why it is not one."
    )


def test_registry_entries_are_well_formed() -> None:
    """Unique names, real classes, and a reason on every entry."""
    names = [seed.name for seed in SEEDS]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert not duplicates, f"duplicate seed names in the registry: {duplicates}"

    for seed in SEEDS:
        assert isinstance(seed.seed_class, SeedClass), (
            f"{seed.name} has a non-SeedClass classification: {seed.seed_class!r}"
        )
        assert seed.reason.strip(), (
            f"{seed.name} has no reason. The reason is what a reviewer reads when "
            "deciding whether reclassifying it is safe."
        )


def test_demo_and_credential_seeds_are_manual_only() -> None:
    """The security pin.

    These seeds create accounts with known passwords, or write into the
    hardcoded demo org. Any of them reclassified to EVERY_DEPLOY or FRESH_ONLY
    would run on the next production deploy — `super_admin` alone would create
    two 'admin123' logins against the legacy /admin panel, which is reachable
    in production.

    Named explicitly rather than inferred, so moving one out of this list is a
    deliberate edit to a test that says why it must not happen.
    """
    must_be_manual = {
        "super_admin",
        "demo_org",
        "demo_admin_user",
        "contact_fields",
        "call_outcomes",
        "core_demo_org",
        "dev_user",
    }
    by_name = {seed.name: seed for seed in SEEDS}

    missing = sorted(must_be_manual - set(by_name))
    assert not missing, (
        f"expected these seeds to exist in the registry: {missing}. If one was "
        "renamed, update this list — do not delete the entry."
    )

    wrong = sorted(
        name for name in must_be_manual if by_name[name].seed_class is not SeedClass.MANUAL_ONLY
    )
    assert not wrong, (
        f"These seeds create known credentials or demo-org rows and MUST stay MANUAL_ONLY: {wrong}"
    )


def test_local_extras_are_real_manual_only_seeds() -> None:
    """`LOCAL_EXTRAS` is the allowlist the unattended runner adds when
    IS_DEVELOPMENT is true, so a typo there means a developer silently loses a
    fixture, and an EVERY_DEPLOY seed listed there would run twice.

    It must never be allowed to name something that is not MANUAL_ONLY: that
    would be a seed running on a server by a route nobody reviewed.
    """
    by_name = {seed.name: seed for seed in SEEDS}

    unknown = sorted(name for name in LOCAL_EXTRAS if name not in by_name)
    assert not unknown, f"LOCAL_EXTRAS names seeds that do not exist: {unknown}"

    not_manual = sorted(
        name for name in LOCAL_EXTRAS if by_name[name].seed_class is not SeedClass.MANUAL_ONLY
    )
    assert not not_manual, (
        "LOCAL_EXTRAS may only contain MANUAL_ONLY seeds — everything else "
        f"already runs unattended: {not_manual}"
    )
