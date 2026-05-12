"""Seed `source=system` custom field definitions for `entity_type='contact'`.

Idempotent — uses the unique key `(org_id, entity_type, field_key)`
to skip rows that already exist. Runs against the demo org seeded by
`seed_demo_org.py`. Prints raw SQL for every row inserted so the
operator can paste it into a non-dev database if needed.

Usage:
    python -m src.app.scripts.seed_contact_system_fields
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.custom_fields.models import CustomFieldDefinition, FieldSource, FieldType
from src.app.scripts.seed_demo_org import DEMO_ORG_ID
from src.app.shared.context import RequestContext, set_context
from src.app.shared.db import async_session


SYSTEM_FIELDS: list[dict[str, Any]] = [
    {
        "field_key": "dob",
        "field_label": "Date of Birth",
        "field_type": FieldType.date,
        "options": None,
        "is_required": False,
        "is_hidden": False,
        "display_order": 0,
        "validation": None,
    },
]


def _render_insert_sql(org_id: uuid.UUID, row: dict[str, Any]) -> str:
    """Equivalent INSERT for operators running against a non-seeded DB.

    Output is single-line, parameter-free SQL suitable for copying into
    psql or pgAdmin. Quoting is conservative — string columns are
    wrapped in $$...$$ to avoid escaping any embedded quotes in labels.
    """
    return (
        "INSERT INTO custom_field_definitions "
        "(org_id, entity_type, field_key, field_label, field_type, "
        "is_required, is_hidden, display_order, source) "
        "VALUES ("
        f"'{org_id}', 'contact', "
        f"$${row['field_key']}$$, "
        f"$${row['field_label']}$$, "
        f"'{row['field_type'].value}', "
        f"{'true' if row['is_required'] else 'false'}, "
        f"{'true' if row['is_hidden'] else 'false'}, "
        f"{row['display_order']}, "
        f"'{FieldSource.system.value}'"
        ") ON CONFLICT (org_id, entity_type, field_key) DO NOTHING;"
    )


async def seed_contact_system_fields() -> None:
    set_context(RequestContext(org_id=DEMO_ORG_ID))

    inserted = 0
    async with async_session() as session:
        for row in SYSTEM_FIELDS:
            existing = (
                await session.execute(
                    select(CustomFieldDefinition.id).where(
                        CustomFieldDefinition.org_id == DEMO_ORG_ID,
                        CustomFieldDefinition.entity_type == "contact",
                        CustomFieldDefinition.field_key == row["field_key"],
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                print(
                    f"skip: contact/{row['field_key']} already exists "
                    f"(id={existing})"
                )
                continue

            stmt = (
                pg_insert(CustomFieldDefinition)
                .values(
                    org_id=DEMO_ORG_ID,
                    entity_type="contact",
                    field_key=row["field_key"],
                    field_label=row["field_label"],
                    field_type=row["field_type"],
                    options=row["options"],
                    is_required=row["is_required"],
                    is_hidden=row["is_hidden"],
                    display_order=row["display_order"],
                    source=FieldSource.system,
                    pack_id=None,
                    validation=row["validation"],
                )
                .on_conflict_do_nothing(
                    index_elements=["org_id", "entity_type", "field_key"]
                )
            )
            await session.execute(stmt)
            inserted += 1

        await session.commit()

    print(f"\nSeeded {inserted} system contact field(s) for org {DEMO_ORG_ID}.")
    print("\nEquivalent SQL (idempotent):")
    for row in SYSTEM_FIELDS:
        print(_render_insert_sql(DEMO_ORG_ID, row))


if __name__ == "__main__":
    asyncio.run(seed_contact_system_fields())
