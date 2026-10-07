"""Seed one real developer login, so a rebuilt local database is usable
without registering through the UI first.

`run.cmd down reset` removes the `db_data` volume (plain `down` and `restart`
keep it). Every rebuild previously meant re-registering by hand before you
could see a single page.

This runs BOTH stages of the real signup flow rather than inserting rows
directly:

  1. `register_user_only`  — user + Owner role template + a pending-template org
  2. `complete_onboarding` — names the org, sets a real template, runs the pack
                             installer (pipelines, stages, lead sources, call
                             outcomes, org settings)

Reusing the service functions matters. Stage 1 alone leaves the org on the
`pending` sentinel template, which sends the account to the onboarding page on
first login instead of the dashboard — and a hand-rolled INSERT would skip the
pack install entirely, producing a login that works into a half-configured org.
That is exactly the kind of difference that makes local behaviour diverge from
a real signup.

GATED TWICE, because `deploy/deploy.sh` runs seeds unconditionally on every
deploy and a developer login on a production box is a back door:

  1. `IS_DEVELOPMENT` must be true — it is false in `config.prod.env`.
  2. Both `DEV_SEED_EMAIL` and `DEV_SEED_PASSWORD` must be set.
     `DEV_SEED_PASSWORD` lives only in `secrets.local.enc.env`, and `.sops.yaml`
     does not list the production server keys as recipients of that file — so a
     prod host cannot decrypt the value even if both other gates were wrong.

Either gate failing makes this a no-op that says why.

Idempotent: skips when the email already exists.

Usage:
    python -m src.app.scripts.seed_dev_user
"""

from __future__ import annotations

import asyncio
import os

from src.app.core.auth.schemas import OnboardingCompleteRequest, RegisterRequest
from src.app.core.auth.service import complete_onboarding, register_user_only
from src.app.core.auth.tokens import decode_token
from src.app.core.users import service as users_service
from src.app.shared.db import async_session

# Core CRM's own pack — the universal platform defaults, no vertical. The
# catalog marks a tile "available" only when a manifest exists on disk; today
# that is base / furniture / real_estate.
DEV_SEED_TEMPLATE_ID = "base"


async def seed_dev_user() -> None:
    if os.getenv("IS_DEVELOPMENT", "false").lower() != "true":
        print("Dev user: skipped (IS_DEVELOPMENT is not true).")
        return

    email = (os.getenv("DEV_SEED_EMAIL") or "").strip()
    password = os.getenv("DEV_SEED_PASSWORD") or ""
    if not email or not password:
        print("Dev user: skipped (DEV_SEED_EMAIL / DEV_SEED_PASSWORD not set).")
        return

    first_name = (os.getenv("DEV_SEED_FIRST_NAME") or "Dev").strip()
    last_name = (os.getenv("DEV_SEED_LAST_NAME") or "User").strip()
    org_name = (os.getenv("DEV_SEED_ORG_NAME") or "").strip() or f"{first_name}'s Workspace"

    async with async_session() as session:
        if await users_service.email_exists(session, email):
            print(f"Dev user: {email} already exists, skipping.")
            return

        registered = await register_user_only(
            session,
            req=RegisterRequest(
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            ),
            ip=None,
            ua="seed_dev_user",
        )

        # Stage 2 needs the caller's identity the way the endpoint has it: the
        # User row, plus the token_id of the session stage 1 just opened. Both
        # come out of the JWT stage 1 minted, so nothing is invented here.
        claims = decode_token(registered.access_token)
        user = await users_service.get_user_by_email(
            session, email, org_id=registered.organization_id, active_only=True
        )
        if user is None:
            raise RuntimeError(f"Dev user {email} was registered but could not be loaded back.")

        await complete_onboarding(
            session,
            user=user,
            current_token_id=claims.token_id,
            req=OnboardingCompleteRequest(
                organization_name=org_name,
                template_id=DEV_SEED_TEMPLATE_ID,
            ),
            ip=None,
            ua="seed_dev_user",
        )

    print(f"Dev user seeded: {email} — org '{org_name}' ({registered.organization_id})")


if __name__ == "__main__":
    asyncio.run(seed_dev_user())
