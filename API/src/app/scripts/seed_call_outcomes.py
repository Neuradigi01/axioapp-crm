"""Seed the 5 generic call outcomes for the demo org.

These are deliberately *generic* (rule 7) — connected / no_answer /
busy / voicemail / wrong_number. The furniture pack adds its own
domain-specific outcomes (quotation_sent, store_visit_booked, …) in
Phase 4.2; this file stays untouched.

Idempotent — uses the unique key `(org_id, key)` to skip rows that
already exist. Equivalent INSERT SQL is printed at the end so an
operator can replay it against a non-seeded DB.

Usage:
    python -m src.app.scripts.seed_call_outcomes
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.calls.models import CallOutcome
from src.app.scripts.seed_demo_org import DEMO_ORG_ID
from src.app.shared.context import RequestContext, set_context
from src.app.shared.db import async_session

DEFAULT_OUTCOMES: list[dict[str, Any]] = [
    {"key": "connected", "label": "Connected", "color": "#10b981", "display_order": 10},
    {"key": "no_answer", "label": "No Answer", "color": "#f59e0b", "display_order": 20},
    {"key": "busy", "label": "Busy", "color": "#f97316", "display_order": 30},
    {"key": "voicemail", "label": "Voicemail", "color": "#6366f1", "display_order": 40},
    {"key": "wrong_number", "label": "Wrong Number", "color": "#ef4444", "display_order": 50},
]


def _render_insert_sql(org_id: uuid.UUID, row: dict[str, Any]) -> str:
    return (
        "INSERT INTO tbl_call_outcomes "
        "(org_id, key, label, color, display_order) "
        "VALUES ("
        f"'{org_id}', "
        f"$${row['key']}$$, "
        f"$${row['label']}$$, "
        f"'{row['color']}', "
        f"{row['display_order']}"
        ") ON CONFLICT (org_id, key) DO NOTHING;"
    )


async def seed_call_outcomes() -> None:
    set_context(RequestContext(org_id=DEMO_ORG_ID))

    inserted = 0
    async with async_session() as session:
        for row in DEFAULT_OUTCOMES:
            existing = (
                await session.execute(
                    select(CallOutcome.id).where(
                        CallOutcome.org_id == DEMO_ORG_ID,
                        CallOutcome.key == row["key"],
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                print(f"skip: call_outcome/{row['key']} already exists (id={existing})")
                continue
            stmt = (
                pg_insert(CallOutcome)
                .values(
                    org_id=DEMO_ORG_ID,
                    key=row["key"],
                    label=row["label"],
                    color=row["color"],
                    display_order=row["display_order"],
                )
                .on_conflict_do_nothing(index_elements=["org_id", "key"])
            )
            await session.execute(stmt)
            inserted += 1

        await session.commit()

    print(f"\nSeeded {inserted} default call outcome(s) for org {DEMO_ORG_ID}.")
    print("\nEquivalent SQL (idempotent):")
    for row in DEFAULT_OUTCOMES:
        print(_render_insert_sql(DEMO_ORG_ID, row))


if __name__ == "__main__":
    asyncio.run(seed_call_outcomes())
