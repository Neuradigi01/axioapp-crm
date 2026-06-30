"""Helpers for enabling Postgres Row-Level Security in Alembic migrations.

Every tenant-scoped table gets the same policy shape:

    CREATE POLICY <policy> ON <table>
    USING (<column> = current_setting('app.org_id', true)::uuid)

The matching session lifecycle hook in `src.app.shared.db` issues
`set_config('app.org_id', <uuid>, true)` at the start of each transaction
from the active `RequestContext`, so policies authorise the connection
without any per-query plumbing.

Notes:
- `current_setting(..., true)` is the "missing_ok" form: when the variable
  hasn't been set on the current transaction it returns NULL, which makes
  the predicate NULL (treated as false) and denies all rows. That is the
  desired default: no tenant context → no rows.
- The migration that creates the tenant root (`organizations`) calls
  `apply_rls("organizations", column="id")` because the org row itself is
  identified by `id`, not by an `org_id` FK.
"""

from __future__ import annotations

from alembic import op

_POLICY_SQL = (
    "CREATE POLICY {policy} ON {table} USING ({column} = current_setting('app.org_id', true)::uuid)"
)


def apply_rls(
    table: str,
    *,
    policy: str = "org_isolation",
    column: str = "org_id",
) -> None:
    """Enable RLS on `table` and create the org-isolation policy."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(_POLICY_SQL.format(policy=policy, table=table, column=column))


def drop_rls(table: str, *, policy: str = "org_isolation") -> None:
    """Drop the policy and disable RLS on `table`. Idempotent."""
    op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
