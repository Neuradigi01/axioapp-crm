"""organizations_rls

Enable Postgres Row-Level Security on the `organizations` table.

`organizations` is the tenant root: a row IS a tenant, so the policy
compares the row's `id` (not an `org_id` FK) against the session-local
`app.org_id` setting populated per request by the DB session hook in
`src.app.shared.db`.

Revision ID: 0002_organizations_rls
Revises: 5fca91020560
Create Date: 2026-05-11 00:00:00.000000

"""
from typing import Sequence, Union

from src.app.shared.rls import apply_rls, drop_rls


revision: str = "0002_organizations_rls"
down_revision: Union[str, None] = "5fca91020560"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    apply_rls("organizations", policy="org_isolation", column="id")


def downgrade() -> None:
    drop_rls("organizations", policy="org_isolation")
