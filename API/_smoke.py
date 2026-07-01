"""Smoke: call get_summary() directly for Ajay's Workspace + list the
card keys returned. Verifies Step 4's 3 new followup cards land."""

import asyncio
import uuid

AJAY_ORG_ID = uuid.UUID("41f9ede9-41b3-44ce-b489-3004566d4068")


async def main() -> None:
    from sqlalchemy import select, text
    from src.app.core.dashboard.service import get_summary
    from src.app.core.users.models import User
    from src.app.shared.context import RequestContext, set_context, reset_context
    from src.app.shared.db import async_session

    token = set_context(RequestContext(org_id=AJAY_ORG_ID, user_id=None))
    try:
        async with async_session() as session:
            # Pick the actual User ORM row for Ajay — service reads
            # .info + .role_id + .org_id + .legacy_uuid.
            row = (await session.execute(
                text(
                    "SELECT ul.id AS login_id, om.role_id, "
                    "       om.organization_id AS org_id "
                    "FROM tbl_user_login ul "
                    "JOIN tbl_organization_members om ON om.user_member_id = ul.id "
                    "WHERE om.organization_id = :org AND om.is_active = true "
                    "LIMIT 1"
                ),
                {"org": str(AJAY_ORG_ID)},
            )).first()
            if row is None:
                print("No user; abort")
                return

            caller = (await session.execute(select(User).where(User.id == row.login_id))).scalar_one()
            # Monkey-patch the org/role attrs that live on
            # tbl_organization_members (not on tbl_user_login).
            caller.__dict__["org_id"] = row.org_id
            caller.__dict__["role_id"] = row.role_id

            resp = await get_summary(session, caller)
            print(f"scope={resp.scope}")
            print("cards:")
            for c in resp.cards:
                delta = ""
                if c.delta_pct is not None:
                    delta = f" (delta={c.delta_pct}%)"
                print(f"  - {c.key} = {c.value} · format={c.format} · link={c.link or '-'}{delta}")

            print()
            followup_keys = [c.key for c in resp.cards if c.key.startswith("followups.")]
            print(f"followup cards found: {followup_keys}")
    finally:
        reset_context(token)


asyncio.run(main())
