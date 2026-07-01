"""Smoke: verify /dashboard/summary honours the new upcoming_scope
query param. Prints today vs next5 for Ajay's Workspace."""

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
            row = (await session.execute(text(
                "SELECT ul.id AS login_id, om.role_id, om.organization_id AS org_id "
                "FROM tbl_user_login ul "
                "JOIN tbl_organization_members om ON om.user_member_id = ul.id "
                "WHERE om.organization_id = :org AND om.is_active = true LIMIT 1"
            ), {"org": str(AJAY_ORG_ID)})).first()
            caller = (await session.execute(select(User).where(User.id == row.login_id))).scalar_one()
            caller.__dict__["org_id"] = row.org_id
            caller.__dict__["role_id"] = row.role_id

            for s in ("today", "next5"):
                resp = await get_summary(session, caller, upcoming_scope=s)
                print(f"\n=== upcoming_scope={s} → {len(resp.upcoming_appointments)} row(s) ===")
                for a in resp.upcoming_appointments:
                    print(f"  {a.starts_at.isoformat()} · {a.title} · with {a.with_contact_name or '-'}")
    finally:
        reset_context(token)


asyncio.run(main())
