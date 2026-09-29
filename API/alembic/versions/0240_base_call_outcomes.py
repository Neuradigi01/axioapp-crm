"""Backfill generic call outcomes for base-pack orgs that have none.

The base pack manifest (``src/app/packs/base/pack.yaml``) shipped with
no ``call_outcomes``, so every org that signed up on the base pack got
an empty Outcome dropdown in "Log a call". The manifest now carries the
five generic outcomes (connected / no_answer / busy / voicemail /
wrong_number); this migration gives existing base-pack orgs the same
set. Orgs that already have any outcome are left alone.

Revision ID: 0240_base_call_outcomes
Revises:     0239_custom_events_minute
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0240_base_call_outcomes"
down_revision: str | None = "0239_custom_events_minute"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same rows as the base pack manifest.
_OUTCOMES_SQL = """
    VALUES
        ('connected',    'Connected',    '#10b981', 10),
        ('no_answer',    'No Answer',    '#f59e0b', 20),
        ('busy',         'Busy',         '#f97316', 30),
        ('voicemail',    'Voicemail',    '#6366f1', 40),
        ('wrong_number', 'Wrong Number', '#ef4444', 50)
"""


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO tbl_call_outcomes (org_id, key, label, color, display_order)
        SELECT o.id, v.key, v.label, v.color, v.display_order
        FROM tbl_organizations o
        CROSS JOIN ({_OUTCOMES_SQL}) AS v(key, label, color, display_order)
        WHERE o.template_id = 'base'
          AND NOT EXISTS (SELECT 1 FROM tbl_call_outcomes c WHERE c.org_id = o.id)
        ON CONFLICT (org_id, key) DO NOTHING
        """
    )


def downgrade() -> None:
    # Remove only the backfilled rows that no call references yet.
    op.execute(
        """
        DELETE FROM tbl_call_outcomes c
        USING tbl_organizations o
        WHERE c.org_id = o.id
          AND o.template_id = 'base'
          AND c.key IN ('connected', 'no_answer', 'busy', 'voicemail', 'wrong_number')
          AND NOT EXISTS (SELECT 1 FROM tbl_calls k WHERE k.outcome_id = c.id)
        """
    )
