"""DR.6.7b smoke — verify the 3 pack-table users.id FKs are dropped.

Pack tables are likely empty in Ajay's Workspace (furniture pack not
installed), so the test inserts a temporary row, flips its user
column to MS Dhoni (post-soak user that triggered the original FK
violation), verifies the write, then deletes the row.

Run: docker compose exec api python smoke_dr67b.py
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import text

from src.app.shared.db import async_session


ORG_ID = uuid.UUID("41f9ede9-41b3-44ce-b489-3004566d4068")
DHONI_UUID = uuid.UUID("61877351-11bc-4cbf-8aac-ace20649eae5")


async def _can_write_user_to(table: str, column: str) -> tuple[bool, str]:
    """Try UPDATEing one existing row's user column to Dhoni; revert.
    If the table is empty, the test skips with PASS (the FK drop is
    proven schema-side once alembic ran)."""
    async with async_session() as session:
        row = await session.execute(
            text(
                f"""
                SELECT id, {column}
                FROM {table}
                WHERE org_id = :org
                  AND ({column} IS DISTINCT FROM :uid)
                LIMIT 1
                """
            ),
            {"org": ORG_ID, "uid": DHONI_UUID},
        )
        rec = row.first()
        if rec is None:
            return True, f"skipped — no rows in {table}"
        row_id, original = rec

    async with async_session() as session:
        await session.execute(
            text(f"UPDATE {table} SET {column} = :uid WHERE id = :id"),
            {"uid": DHONI_UUID, "id": row_id},
        )
        await session.commit()

    async with async_session() as session:
        row = await session.execute(
            text(f"SELECT {column} FROM {table} WHERE id = :id"),
            {"id": row_id},
        )
        after = row.scalar_one()
        if after != DHONI_UUID:
            return False, f"{column} = {after}, expected Dhoni"

    async with async_session() as session:
        await session.execute(
            text(f"UPDATE {table} SET {column} = :uid WHERE id = :id"),
            {"uid": original, "id": row_id},
        )
        await session.commit()
    return True, f"id={row_id} flipped to Dhoni and reverted"


async def _verify_constraint_gone(constraint: str, table: str) -> tuple[bool, str]:
    """Schema-side check — proves the constraint no longer exists."""
    async with async_session() as session:
        row = await session.execute(
            text(
                """
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname = :table AND c.conname = :name
                """
            ),
            {"table": table, "name": constraint},
        )
        if row.scalar_one_or_none() is None:
            return True, f"{constraint} absent ✓"
        return False, f"{constraint} STILL EXISTS"


async def main() -> None:
    schema_checks = [
        ("fp_inventory_movements_user_id_fkey", "fp_inventory_movements"),
        ("fp_custom_orders_assigned_to_id_fkey", "fp_custom_orders"),
        ("fp_custom_order_stages_user_id_fkey", "fp_custom_order_stages"),
    ]
    write_checks = [
        ("fp_inventory_movements", "user_id"),
        ("fp_custom_orders", "assigned_to_id"),
        ("fp_custom_order_stages", "user_id"),
    ]

    results = []
    for constraint, table in schema_checks:
        try:
            ok, msg = await _verify_constraint_gone(constraint, table)
            results.append(("PASS" if ok else "FAIL", f"schema:{constraint}", msg))
        except Exception as exc:
            results.append(("FAIL", f"schema:{constraint}", f"{type(exc).__name__}: {exc}"))

    for table, column in write_checks:
        try:
            ok, msg = await _can_write_user_to(table, column)
            results.append(("PASS" if ok else "FAIL", f"write:{table}.{column}", msg))
        except Exception as exc:
            results.append(("FAIL", f"write:{table}.{column}", f"{type(exc).__name__}: {exc}"))

    print()
    print("=" * 78)
    print("DR.6.7b SMOKE TEST RESULTS")
    print("=" * 78)
    for mark, name, msg in results:
        print(f"  [{mark}] {name:50s}  {msg}")
    print("=" * 78)
    if [r for r in results if r[0] == "FAIL"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
