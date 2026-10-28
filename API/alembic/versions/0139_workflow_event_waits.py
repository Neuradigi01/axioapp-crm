"""Workflow event-wait registry (``tasks/workflows`` Step 11).

NEW table ``tbl_workflow_event_waits`` — one row per parked
``flow_control.wait_for_event`` node. The Step-5 trigger handler
checks this table on every published event + resumes matching
runs on the ``event_received`` outbound edge. The Step-11 beat
sweep handles the timeout path: expired waits resume on the
``timeout`` outbound edge.

Schema:

  id            UUID PK
  org_id        UUID FK tbl_organizations.id
  run_id        UUID FK tbl_workflow_runs.id ON DELETE CASCADE
  node_id       TEXT   (the node in the workflow's graph)
  event_type    TEXT   (e.g. ``quote.viewed``)
  contact_id    UUID nullable (when set, only matching contact's
                event resumes; when null any event of the type
                resumes)
  expires_at    TIMESTAMPTZ
  created_at    TIMESTAMPTZ default now()

Indexes:
  - Partial ``(org_id, event_type, contact_id) WHERE expires_at > now()``
    on the resume-lookup hot path.
  - Partial ``(expires_at) WHERE expires_at > now()`` on the beat
    sweep's "find waits due to expire next" path.

RLS policy matches every other tenant-scoped table — the
``current_setting('app.current_org_id')`` gate.

Chains after ``0138_org_settings_routing_state``. Reversible.

Revision ID: 0139_workflow_event_waits
Revises: 0138_org_settings_routing_state
Create Date: 2026-06-29 21:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0139_workflow_event_waits"
down_revision: Union[str, None] = "0138_org_settings_routing_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tbl_workflow_event_waits",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tbl_contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Resume-lookup hot path. The trigger handler queries by
    # (org_id, event_type, contact_id) on every published event.
    # Non-partial because Postgres requires IMMUTABLE functions in
    # index predicates + ``now()`` isn't immutable. The expired-wait
    # cleanup path (Step-11 ``expire_waits`` beat task) deletes rows
    # past their TTL so the index stays bounded; CASCADE on parent
    # run deletion provides the second cleanup channel.
    op.create_index(
        "ix_workflow_event_waits_lookup",
        "tbl_workflow_event_waits",
        ["org_id", "event_type", "contact_id"],
    )
    # Sweep target for the beat task.
    op.create_index(
        "ix_workflow_event_waits_expiry_sweep",
        "tbl_workflow_event_waits",
        ["expires_at"],
    )

    # RLS policy.
    op.execute("ALTER TABLE tbl_workflow_event_waits ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tbl_workflow_event_waits_tenant_isolation
            ON tbl_workflow_event_waits
            USING (org_id::text = current_setting('app.current_org_id', true))
            WITH CHECK (org_id::text = current_setting('app.current_org_id', true))
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tbl_workflow_event_waits_tenant_isolation "
        "ON tbl_workflow_event_waits"
    )
    op.drop_index(
        "ix_workflow_event_waits_expiry_sweep",
        table_name="tbl_workflow_event_waits",
    )
    op.drop_index(
        "ix_workflow_event_waits_lookup",
        table_name="tbl_workflow_event_waits",
    )
    op.drop_table("tbl_workflow_event_waits")
