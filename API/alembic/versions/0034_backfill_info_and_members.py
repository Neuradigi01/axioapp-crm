"""Backfill tbl_user_info + tbl_organization_members from tbl_user_login

Step DR.7.2 of the three-table split. Reads the FurnitureCRM-shaped
columns DR.6.1 stuffed onto `tbl_user_login` (email / full_name / phone
/ org_id / role_id / is_demo / is_active / created_at) and fans them
out into the two destination tables:

  - tbl_user_info: one row per FurnitureCRM user (member_id = login.id).
    `full_name` is split on the first whitespace into first/last; users
    with no last name get last_name = ''.
  - tbl_organization_members: one row per (org, user) pair, recording
    role + is_demo + is_active + joined_at.

Idempotent:

  - tbl_user_info has UNIQUE(member_id) — we guard with NOT EXISTS so
    re-running the migration is a no-op.
  - tbl_organization_members has UNIQUE(org_id, user_member_id) — same
    NOT EXISTS guard.

The legacy USR29684795 row in `tbl_user_login` has NULL email/org/role,
so it's filtered out by the `WHERE email IS NOT NULL` predicate and
neither table is touched on its behalf. Its existing tbl_user_info row
(seeded by the legacy template) is also untouched.

Revision ID: 0034_backfill_info_and_members
Revises: 0033_tbl_organization_members
Create Date: 2026-05-15 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0034_backfill_info_and_members"
down_revision: Union[str, None] = "0033_tbl_organization_members"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    src_rows = conn.execute(
        sa.text(
            """
            SELECT
                id,
                email::text     AS email,
                full_name,
                phone,
                org_id,
                role_id,
                is_demo,
                is_active,
                created_at
            FROM tbl_user_login
            WHERE email IS NOT NULL
            ORDER BY id
            """
        )
    ).all()

    for r in src_rows:
        full = (r.full_name or "").strip()
        parts = full.split(maxsplit=1)
        first_name = parts[0] if parts else ""
        last_name = parts[1] if len(parts) > 1 else ""

        # 1) Profile row in tbl_user_info (1:1 with tbl_user_login).
        conn.execute(
            sa.text(
                """
                INSERT INTO tbl_user_info (
                    member_id, first_name, last_name, email, mobile_no,
                    is_email_verified, is_mobile_verified, joining_date
                )
                SELECT :member_id, :first_name, :last_name, :email, :mobile_no,
                       FALSE, FALSE, :joining_date
                WHERE NOT EXISTS (
                    SELECT 1 FROM tbl_user_info WHERE member_id = :member_id
                )
                """
            ),
            {
                "member_id": r.id,
                "first_name": first_name,
                "last_name": last_name,
                "email": r.email,
                "mobile_no": r.phone,
                "joining_date": r.created_at,
            },
        )

        # 2) Membership row (org + role + per-(org,user) flags).
        if r.org_id is None or r.role_id is None:
            continue
        conn.execute(
            sa.text(
                """
                INSERT INTO tbl_organization_members (
                    organization_id, user_member_id, role_id,
                    status, is_active, is_demo, joined_at
                )
                SELECT :org_id, :user_member_id, :role_id,
                       'active', :is_active, :is_demo, :joined_at
                WHERE NOT EXISTS (
                    SELECT 1 FROM tbl_organization_members
                    WHERE organization_id = :org_id
                      AND user_member_id = :user_member_id
                )
                """
            ),
            {
                "org_id": r.org_id,
                "user_member_id": r.id,
                "role_id": r.role_id,
                "is_active": r.is_active,
                "is_demo": r.is_demo,
                "joined_at": r.created_at,
            },
        )


def downgrade() -> None:
    # Only remove rows we inserted: those for FurnitureCRM members
    # (i.e. tbl_user_login rows that still carry a non-NULL email column,
    # which DR.6.1 put there and DR.7.5 hasn't dropped yet).
    op.execute(
        """
        DELETE FROM tbl_organization_members
        WHERE user_member_id IN (
            SELECT id FROM tbl_user_login WHERE email IS NOT NULL
        )
        """
    )
    op.execute(
        """
        DELETE FROM tbl_user_info
        WHERE member_id IN (
            SELECT id FROM tbl_user_login WHERE email IS NOT NULL
        )
        """
    )
