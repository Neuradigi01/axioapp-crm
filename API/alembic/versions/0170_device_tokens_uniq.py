"""tbl_device_tokens — swap standalone `fcm_token` UNIQUE for composite
UNIQUE on (user_type, member_id, fcm_token).

The old unique-on-token-alone constraint let register_token upsert the
row to whichever caller sent the FCM token last. An attacker who
sniffed / phished / re-used another user's token could POST /device-
tokens/register and re-link the row to their own account, silently
diverting every future push notification. Composite unique fixes this:
same physical device can still register under two accounts (one row
each), but no row is ever silently re-parented.

Revision ID: 0170_device_tokens_uniq
Revises:     0169_email_smtp_senders
Create Date: 2026-07-29
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0170_device_tokens_uniq"
down_revision = "0169_email_smtp_senders"
branch_labels = None
depends_on = None

# Legacy migration a1b2c3d4e5f6 seeded the standalone unique constraint
# via a column-level `unique=True`. Postgres materialised it as an
# implicit index; the constraint name follows the SQLAlchemy default
# `tbl_device_tokens_fcm_token_key`.
_OLD_UNIQUE = "tbl_device_tokens_fcm_token_key"
_NEW_UNIQUE = "uq_device_tokens_user_token"


def upgrade() -> None:
    # Deduplicate any historical rows before we can safely tighten the
    # constraint: keep the highest-id (i.e. most recently created) row
    # for each (user_type, member_id, fcm_token) triplet, drop older
    # dupes. In practice this touches zero rows on a clean deployment;
    # exists for staging DBs that saw the hijack path.
    op.execute(
        """
        DELETE FROM tbl_device_tokens t
        USING tbl_device_tokens t2
        WHERE t.user_type = t2.user_type
          AND t.member_id = t2.member_id
          AND t.fcm_token = t2.fcm_token
          AND t.id < t2.id
        """
    )

    op.drop_constraint(_OLD_UNIQUE, "tbl_device_tokens", type_="unique")
    op.create_unique_constraint(
        _NEW_UNIQUE,
        "tbl_device_tokens",
        ["user_type", "member_id", "fcm_token"],
    )


def downgrade() -> None:
    # Reverting is only safe if no two rows share the same fcm_token
    # across users. Bail out with a clear error if they do rather than
    # silently corrupting data.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM tbl_device_tokens
                GROUP BY fcm_token HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'downgrade blocked: multiple rows share fcm_token; '
                    'the old unique constraint cannot be restored without loss';
            END IF;
        END
        $$;
        """
    )
    op.drop_constraint(_NEW_UNIQUE, "tbl_device_tokens", type_="unique")
    op.create_unique_constraint(_OLD_UNIQUE, "tbl_device_tokens", ["fcm_token"])
