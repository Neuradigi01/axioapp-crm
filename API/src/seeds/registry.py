"""Every seed declares WHEN it is safe to run. There is no default.

`deploy/deploy.sh` runs `run.sh seed` on every deploy and names no seeds — it
cannot, because reference data that ships WITH a commit (a new route, a new
permission) has to reach the database that commit needs it in, and a step
someone runs by hand afterwards is a step that gets missed the moment CI
deploys with nobody watching. The symptom is a missing menu row and nothing in
the log explaining why.

So the decision moves here, next to the seeds, instead of living as a list in a
shell script that has to be kept in sync.

Three classes, and every seed is in exactly one
(`tests/test_seed_classification.py` fails CI otherwise):

**EVERY_DEPLOY** — idempotent upserts that never delete. Safe unattended on any
environment, including production with real customers on it.

**FRESH_ONLY** — anything that RECONCILES, i.e. deletes rows its source no
longer lists. Correct when an operator applies a change deliberately; wrong as
a side effect of deploying, because a row someone added by hand disappears
without anyone being asked. Gated on whether the database holds real data —
NOT on the environment name. Production on day zero is genuinely fresh and
should get everything; a local database with real work in it should not lose
rows either. What deserves protection is the data; the environment is only a
proxy for it.

**MANUAL_ONLY** — demo fixtures and anything carrying a known credential. Never
runs on a server, ever. The unattended runner skips these unless
`IS_DEVELOPMENT` is true, and they can always be named explicitly by a human.

Nothing is FRESH_ONLY today. The class and its gate exist anyway, because the
alternative is that the first reconciling seed someone writes inherits the
dangerous default of running on every deploy against live data.
"""

from __future__ import annotations

import enum
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from src.app.scripts.seed_admin_user import seed_admin_user
from src.app.scripts.seed_call_outcomes import seed_call_outcomes
from src.app.scripts.seed_contact_system_fields import seed_contact_system_fields
from src.app.scripts.seed_core_demo_org import seed_core_demo_org
from src.app.scripts.seed_demo_org import seed_demo_org
from src.app.scripts.seed_dev_user import seed_dev_user
from src.seeds.seed_admin import seed_super_admin
from src.seeds.seed_countries import seed_countries, seed_states
from src.seeds.seed_routes import seed_routes


class SeedClass(enum.Enum):
    EVERY_DEPLOY = "every_deploy"
    FRESH_ONLY = "fresh_only"
    MANUAL_ONLY = "manual_only"


@dataclass(frozen=True)
class Seed:
    """One seed and the rule for when it may run.

    `reason` is not decoration — it is what a reviewer reads when deciding
    whether a reclassification is safe, and what the runner prints when it
    skips something.
    """

    name: str
    run: Callable[[], Awaitable[None]]
    seed_class: SeedClass
    reason: str


SEEDS: tuple[Seed, ...] = (
    Seed(
        name="routes",
        run=seed_routes,
        seed_class=SeedClass.EVERY_DEPLOY,
        reason=(
            "Frontend route table. Pure upsert — skips any control_id that already "
            "exists and never deletes. A commit that adds a page ships its route "
            "here, so it must land on the same deploy or the page 404s."
        ),
    ),
    Seed(
        name="countries",
        run=seed_countries,
        seed_class=SeedClass.EVERY_DEPLOY,
        reason="Static ISO reference data, insert-if-missing. Never deletes.",
    ),
    Seed(
        name="states",
        run=seed_states,
        seed_class=SeedClass.EVERY_DEPLOY,
        reason=(
            "Static ISO reference data, insert-if-missing. Runs after countries — "
            "rows whose country is absent are skipped, not failed."
        ),
    ),
    Seed(
        name="super_admin",
        run=seed_super_admin,
        seed_class=SeedClass.MANUAL_ONLY,
        reason=(
            "Creates the legacy admin-panel accounts 'DevAdmin' and 'admin', both "
            "with the password 'admin123'. The legacy /admin login is reachable in "
            "production, so running this unattended would put two known-credential "
            "super admins on a live server. Name it explicitly, on a machine where "
            "that is what you want."
        ),
    ),
    Seed(
        name="demo_org",
        run=seed_demo_org,
        seed_class=SeedClass.MANUAL_ONLY,
        reason="Demo fixture — the fixed-UUID 'Demo Furniture Store' organization.",
    ),
    Seed(
        name="demo_admin_user",
        run=seed_admin_user,
        seed_class=SeedClass.MANUAL_ONLY,
        reason=(
            "Demo fixture — admin@demo.local / Admin@123 in the demo org, plus a "
            "tbl_demo_credentials row that stores that password in PLAINTEXT to back "
            "the dev demo-login pill. Belongs nowhere near a server."
        ),
    ),
    Seed(
        name="contact_fields",
        run=seed_contact_system_fields,
        seed_class=SeedClass.MANUAL_ONLY,
        reason=(
            "Writes only into the hardcoded demo org id, so it is a demo fixture "
            "despite the generic name. Real orgs get their custom fields from the "
            "pack installer at signup, not from here."
        ),
    ),
    Seed(
        name="call_outcomes",
        run=seed_call_outcomes,
        seed_class=SeedClass.MANUAL_ONLY,
        reason=(
            "Writes only into the hardcoded demo org id — same story as "
            "contact_fields. Real orgs get call outcomes from the pack installer."
        ),
    ),
    Seed(
        name="core_demo_org",
        run=seed_core_demo_org,
        seed_class=SeedClass.MANUAL_ONLY,
        reason=(
            "Demo fixture — the second 'core-demo' organization used to show a "
            "pack-less sidebar beside the furniture one, with three fixed users and "
            "known passwords. Never wired into the runner before this registry "
            "existed; it was a standalone script nothing called."
        ),
    ),
    Seed(
        name="dev_user",
        run=seed_dev_user,
        seed_class=SeedClass.MANUAL_ONLY,
        reason=(
            "Creates a developer login from DEV_SEED_EMAIL / DEV_SEED_PASSWORD. The "
            "seed refuses to run unless IS_DEVELOPMENT is true and both variables "
            "are set, and its password is only in secrets.local.enc.env — but it is "
            "classified here too so the classification, not the seed's own guard, is "
            "the thing a reviewer has to get wrong."
        ),
    ),
)


def seeds_in(seed_class: SeedClass) -> tuple[Seed, ...]:
    return tuple(s for s in SEEDS if s.seed_class is seed_class)


def seed_by_name(name: str) -> Seed | None:
    return next((s for s in SEEDS if s.name == name), None)
