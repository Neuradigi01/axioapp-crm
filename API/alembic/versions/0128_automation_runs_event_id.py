"""automation: add event_id to tbl_automation_runs for idempotency

Step 4 of ``tasks/automation-engine/`` wires the bus → dispatcher →
Celery pipeline. The dispatcher needs an idempotency key so a
re-published event (Celery at-least-once + retried publishers +
manual replay scripts all produce duplicates) doesn't insert a
second run row + double-fire the send.

The natural key is ``(trigger_id, event_id)`` where ``event_id`` is
a publisher-supplied string (typically the originating row's PK).
When a publisher omits ``event_id``, the bus auto-fills a fresh
UUID — idempotency becomes per-fire (no dedupe).

Schema delta:

  * ``tbl_automation_runs.event_id`` text NOT NULL, default
    ``gen_random_uuid()::text``. Default backfills existing rows so
    the NOT NULL constraint installs cleanly.
  * Unique partial index ``uq_automation_runs_trigger_event_id``
    on ``(trigger_id, event_id)`` WHERE ``event_id IS NOT NULL``
    (partial guards against the impossible-but-defensive NULL
    case + matches the existing pattern in
    ``ix_automation_runs_org_status_scheduled``).

Chains after ``0127_bf_automations_perm``. Reversible.

Revision ID: 0128_run_event_id
Revises: 0127_bf_automations_perm
Create Date: 2026-06-26 04:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0128_run_event_id"
down_revision: Union[str, None] = "0127_bf_automations_perm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tbl_automation_runs",
        sa.Column(
            "event_id",
            sa.Text(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()::text"),
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_automation_runs_trigger_event_id "
        "ON tbl_automation_runs (trigger_id, event_id) "
        "WHERE event_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_automation_runs_trigger_event_id")
    op.drop_column("tbl_automation_runs", "event_id")
