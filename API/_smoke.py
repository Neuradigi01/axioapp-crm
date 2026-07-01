"""Smoke:
   1. Verify /tasks/{id}/mark-missed flips open → missed for an
      overdue task, refuses on already-missed with 409.
   2. Verify the grooming task auto-closes a task with due_at > 7d
      in the past.
Uses Ajay's Workspace org.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

AJAY_ORG = "41f9ede9-41b3-44ce-b489-3004566d4068"
AJAY_UUID = "dff5c609-c88f-4219-bbda-3480ee00dec0"

url = f"postgresql+asyncpg://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}@{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_NAME']}"


async def main() -> None:
    now = datetime.now(UTC)

    e = create_async_engine(url)
    async with e.begin() as c:
        # Seed one overdue-open task + one >7d-open task for grooming
        overdue_id = str(uuid.uuid4())
        stale_id = str(uuid.uuid4())
        await c.execute(text("""
            INSERT INTO tbl_tasks (id, org_id, title, due_at, assigned_to_id,
                                   status, priority, created_at, updated_at)
            VALUES (:id1, :org, '[smoke6] overdue for mark-missed', :yesterday,
                    :assign, 'open', 'med', :now, :now),
                   (:id2, :org, '[smoke6] >8d old for grooming', :old,
                    :assign, 'open', 'med', :now, :now)
        """), {
            "id1": overdue_id, "id2": stale_id, "org": AJAY_ORG,
            "assign": AJAY_UUID,
            "yesterday": now - timedelta(days=1),
            "old": now - timedelta(days=8),
            "now": now,
        })

    # Direct service call — mimic the endpoint's contract
    # Eagerly import ORM model modules so string-based FK references
    # ('tbl_organizations.id') resolve at flush time.
    from src.app.core.tenants import models as _tenants  # noqa: F401
    from src.app.core.tasks.service import mark_task_missed
    from src.app.shared.context import RequestContext, set_context, reset_context
    from src.app.shared.db import async_session
    from fastapi import HTTPException

    token = set_context(RequestContext(org_id=uuid.UUID(AJAY_ORG), user_id=None))
    try:
        async with async_session() as session:
            print("=== 1. mark_task_missed happy path ===")
            row = await mark_task_missed(session, task_id=uuid.UUID(overdue_id))
            print(f"  status after call: {row.status.value}  (expected: missed)")

        async with async_session() as session:
            print("=== 2. mark_task_missed on already-missed → 409 ===")
            try:
                await mark_task_missed(session, task_id=uuid.UUID(overdue_id))
                print("  UNEXPECTED: no 409 raised")
            except HTTPException as ex:
                print(f"  HTTP {ex.status_code}: {ex.detail}")
    finally:
        reset_context(token)

    # 3. Grooming task — call the async coroutine directly to avoid
    # nesting asyncio.run() inside the outer loop. Celery worker
    # invokes it via the sync wrapper in production.
    from src.app.core.tasks.tasks import _groom_stale_open_tasks_async
    print()
    print("=== 3. groom_stale_open_tasks ===")
    result = await _groom_stale_open_tasks_async()
    print(f"  result: {result}")

    # Verify the stale row is now missed
    async with e.connect() as c:
        r = (await c.execute(text(
            "SELECT status FROM tbl_tasks WHERE id = :id"
        ), {"id": stale_id})).scalar_one()
        print(f"  stale row status: {r}  (expected: missed)")

    # Cleanup
    async with e.begin() as c:
        await c.execute(text(
            "DELETE FROM tbl_tasks WHERE title LIKE '[smoke6]%'"
        ))
    print("\ncleanup: deleted [smoke6] rows")
    await e.dispose()


asyncio.run(main())
