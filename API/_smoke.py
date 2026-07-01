"""Smoke: call get_followups() directly with an org context, bypassing
HTTP + login. Uses Ajay's Workspace org id."""

import asyncio
import uuid

AJAY_ORG_ID = uuid.UUID("41f9ede9-41b3-44ce-b489-3004566d4068")


async def main() -> None:
    from src.app.core.dashboard.service import get_followups
    from src.app.core.tenants import data_access as _tenants_da
    from src.app.core.users import data_access as _users_da
    from src.app.shared.context import RequestContext, set_context, reset_context
    from src.app.shared.db import async_session

    token = set_context(RequestContext(org_id=AJAY_ORG_ID, user_id=None))
    try:
        async with async_session() as session:
            # Pick a Owner-like caller for the org — any active user.
            from sqlalchemy import text
            # Discover the membership FK column name once.
            cols = [r[0] for r in (await session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'tbl_organization_members'"
                )
            )).all()]
            print(f"tbl_organization_members columns: {cols}")
            row = (await session.execute(
                text(
                    "SELECT ul.id AS login_id, ul.legacy_uuid, om.role_id, "
                    "       om.organization_id AS org_id "
                    "FROM tbl_user_login ul "
                    "JOIN tbl_organization_members om ON om.user_member_id = ul.id "
                    "WHERE om.organization_id = :org "
                    "  AND om.is_active = true "
                    "LIMIT 1"
                ),
                {"org": str(AJAY_ORG_ID)},
            )).first()
            if row is None:
                print("No user in org — cannot smoke test")
                return

            print(f"caller: login_id={row.login_id} "
                  f"legacy_uuid={row.legacy_uuid} "
                  f"role={row.role_id} org={row.org_id}")

            # Build a minimal User-like stub with the fields the service reads.
            class _Caller:
                id = row.login_id
                legacy_uuid = row.legacy_uuid
                role_id = row.role_id
                org_id = row.org_id

            for bucket in ("today", "pending", "completed_today", "overdue", "missed"):
                resp = await get_followups(session, _Caller(), bucket=bucket, page_size=3)
                print(f"\n=== bucket={bucket} ===")
                print(f"scope={resp.scope} total={resp.total} "
                      f"counts={resp.counts.model_dump()}")
                for it in resp.items:
                    print(f"  - {it.title!r} due={it.due_at} "
                          f"status={it.status} priority={it.priority} "
                          f"type={it.followup_type} "
                          f"assignee={it.assigned_to.name} "
                          f"linked={it.linked_entity.type + ':' + it.linked_entity.label if it.linked_entity else '-'}")
    finally:
        reset_context(token)


asyncio.run(main())
