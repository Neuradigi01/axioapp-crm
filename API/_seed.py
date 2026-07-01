"""Seed a handful of tasks for Ajay's Workspace to smoke the
follow-ups endpoint. Idempotent — only inserts if none of the seeded
title strings already exist for the org."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

AJAY_ORG = "41f9ede9-41b3-44ce-b489-3004566d4068"
AJAY_UUID = "dff5c609-c88f-4219-bbda-3480ee00dec0"  # matches tbl_user_login.legacy_uuid

url = f"postgresql+asyncpg://{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}@{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_NAME']}"


async def main() -> None:
    now = datetime.now(UTC)
    today_10am = now.replace(hour=10, minute=0, second=0, microsecond=0)

    # Row template: (title, offset_days_from_today_10am, status, priority, followup_type)
    seeds = [
        ("[smoke] Send quote PDF today",         0, "open",   "high", "email"),
        ("[smoke] Call Rahul re: sofa",          0, "open",   "med",  "call"),
        ("[smoke] WhatsApp Priya swatches",      0, "open",   "low",  "whatsapp"),
        ("[smoke] Send done-today confirmation", 0, "done",   "med",  "email"),
        ("[smoke] Overdue: Follow up Yuva",     -1, "open",   "med",  "call"),
        ("[smoke] Missed: Cust unreachable",    -3, "missed", "low",  "call"),
        ("[smoke] Cancelled sample task",       -1, "cancelled", "low", None),
    ]

    e = create_async_engine(url)
    async with e.begin() as c:
        exists = await c.execute(text(
            "SELECT COUNT(*) FROM tbl_tasks WHERE org_id = :o AND title LIKE '[smoke]%'"
        ), {"o": AJAY_ORG})
        if exists.scalar_one() > 0:
            print("smoke tasks already exist; skipping seed")
            return

        for title, offset_days, status, priority, ftype in seeds:
            due = today_10am + timedelta(days=offset_days)
            # Only shift `updated_at` for missed/done rows so the
            # "completed_today" + "missed_last_7d" buckets pick them up.
            if status == "done":
                # Simulate "completed today" by keeping updated_at = now.
                updated = now
            elif status == "missed":
                updated = now - timedelta(days=1)  # missed 1 day ago
            else:
                updated = now

            await c.execute(text("""
                INSERT INTO tbl_tasks (
                    id, org_id, title, description, due_at,
                    assigned_to_id, status, priority, followup_type,
                    created_at, updated_at
                ) VALUES (
                    :id, :org, :title, :desc, :due,
                    :assigned, :status, :priority, :ftype,
                    :now, :updated
                )
            """), {
                "id": str(uuid.uuid4()),
                "org": AJAY_ORG,
                "title": title,
                "desc": ("Follow-up notes: customer requested v2 with fabric "
                         "swatches, budget confirmed at 45k, delivery mid-July"),
                "due": due,
                "assigned": AJAY_UUID,
                "status": status,
                "priority": priority,
                "ftype": ftype,
                "now": now,
                "updated": updated,
            })
            print(f"seeded: {title}")

    await e.dispose()


asyncio.run(main())
