"""backfill: single-step workflow mirror for every existing automation.

Step 1 of ``tasks/workflows-absorb-automation/`` — walks every
``tbl_automation_triggers`` row in every org, creates a matching
single-step workflow (``trigger`` → optional ``flow.wait`` →
``send.<channel>``) in ``tbl_workflows`` + v=1 in
``tbl_workflow_versions``, then soft-disables the source
(``enabled = false``) and stores the mirror id in
``tbl_automation_triggers.migrated_to_workflow_id`` so redirects and
the reversible downgrade can look it up.

Order within the txn: the workflow mirror is inserted FIRST (so the
new id is available) and the source row is disabled + linked in a
single UPDATE. Alembic runs the migration inside one transaction so
no external observer sees an intermediate state where both engines are
active for the same event; the dispatcher's ``enabled=true`` filter
plus the migration's soft-disable together guarantee zero duplicate
sends across the whole cutover.

Channel → node-type mapping matches the workflow action registry
(``core/workflows/actions/send.py``):

    email      → send.email
    whatsapp   → send.whatsapp
    sms        → send.sms
    facebook   → send.facebook
    instagram  → send.instagram
    push       → send.push

``web`` is not a valid send channel (no adapter registered) so any
automation carrying it is skipped with a logged warning — a fresh
install shouldn't have any such rows, this is a defence-in-depth.

Name collisions: when an operator has already created a workflow with
the exact same name as the source automation, the mirror lands with
the suffix `` (from automation)`` so both rows stay distinguishable in
the UI.

Idempotency: rows already carrying ``migrated_to_workflow_id`` are
skipped, so a re-run of this migration is a no-op.

Downgrade: for every automation carrying a FK, delete its mirror
workflow + versions + step_runs + runs, restore ``enabled = true``,
clear the FK. Automations that were already ``enabled=false`` before
this migration ran get their pre-migration state back too (the
downgrade sets ``enabled=true`` unconditionally — the operator can
re-disable if they need to; false-positive re-enable is far less
harmful than leaving the row permanently dark).

Revision ID: 0176_bf_autos_to_workflows
Revises:     0175_automation_migrated_fk
Create Date: 2026-08-05
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text as sql_text

from alembic import op

revision: str = "0176_bf_autos_to_workflows"
down_revision: str | None = "0175_automation_migrated_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


logger = logging.getLogger("alembic.workflows.absorb_automation")


# Channels an automation could carry that map cleanly to a workflow
# send action. Keys are the string values stored in
# ``tbl_automation_triggers.channel`` (from the ``conversation_channel``
# PG enum); values are the workflow node ``type`` string registered by
# ``core.workflows.actions.send.register``.
_CHANNEL_TO_NODE_TYPE: dict[str, str] = {
    "email": "send.email",
    "whatsapp": "send.whatsapp",
    "sms": "send.sms",
    "facebook": "send.facebook",
    "instagram": "send.instagram",
    "push": "send.push",
}

# Canonical suffix used to disambiguate mirror workflows whose source
# automation name already exists as a workflow in the same org.
_COLLISION_SUFFIX = " (from automation)"

# Sentinel category so the workflows page + the reversible downgrade
# can identify mirror rows without a schema change.
_MIGRATED_CATEGORY = "Migrated Automation"


def _short(prefix: str) -> str:
    """Deterministic-ish short node id — matches the gallery seed
    convention (``t-<hex8>`` / ``s-<hex8>``). Uniqueness per graph is
    guaranteed by the fresh uuid4."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _build_graph(
    *,
    event_type: str,
    conditions: dict[str, Any] | None,
    channel_node_type: str,
    template_id: str,
    recipient_resolver: str,
    recipient_resolver_config: dict[str, Any] | None,
    delay_seconds: int,
) -> dict[str, Any]:
    """Compose the ``{nodes, edges}`` JSONB for a single-step mirror
    workflow. Layout: trigger → (optional wait) → send. No goal
    node — the send is the terminal action and ``goal_node_id`` stays
    NULL on the ``tbl_workflows`` row."""
    trigger_id = _short("t")
    send_id = _short("s")
    nodes: list[dict[str, Any]] = [
        {
            "id": trigger_id,
            "type": "trigger",
            "position": {"x": 240, "y": 80},
            "config": {
                "label": "Trigger",
                "event_type": event_type,
                "re_enrollment_rule": "once",
                "conditions": conditions or None,
            },
        },
    ]
    edges: list[dict[str, Any]] = []
    previous = trigger_id

    if delay_seconds and delay_seconds > 0:
        wait_id = _short("w")
        nodes.append(
            {
                "id": wait_id,
                "type": "flow.wait",
                "position": {"x": 240, "y": 220},
                "config": {
                    "label": "Wait",
                    "delay_seconds": int(delay_seconds),
                    # Validator requires ``max_wait_seconds`` on wait
                    # nodes; engine reads ``delay_seconds`` first + falls
                    # back to ``max_wait_seconds`` so both keys carry the
                    # same value.
                    "max_wait_seconds": int(delay_seconds),
                },
            }
        )
        edges.append(
            {
                "id": _short("e"),
                "source": previous,
                "target": wait_id,
                "label": None,
            }
        )
        previous = wait_id

    nodes.append(
        {
            "id": send_id,
            "type": channel_node_type,
            "position": {"x": 240, "y": 220 + (140 if delay_seconds and delay_seconds > 0 else 0)},
            "config": {
                "label": "Send",
                "template_id": template_id,
                "recipient_resolver": recipient_resolver,
                "recipient_resolver_config": recipient_resolver_config or {},
            },
        }
    )
    edges.append(
        {
            "id": _short("e"),
            "source": previous,
            "target": send_id,
            "label": None,
        }
    )

    return {"nodes": nodes, "edges": edges}


def _make_description(*, source_name: str, event_type: str, channel: str) -> str:
    return (
        f'Migrated from single-step automation "{source_name}". '
        f"Trigger: {event_type}. Sends via {channel}."
    )


def upgrade() -> None:
    bind = op.get_bind()

    # Fetch every automation not yet migrated. We ORDER BY id so the
    # mirror insertion order is deterministic — makes test assertions
    # + operator report SQL stable across re-runs.
    rows = (
        bind.execute(
            sql_text(
                """
            SELECT
                id::text        AS id,
                org_id::text    AS org_id,
                name            AS name,
                enabled         AS enabled,
                event_type      AS event_type,
                conditions      AS conditions,
                channel::text   AS channel,
                template_id::text AS template_id,
                delay_seconds   AS delay_seconds,
                recipient_resolver AS recipient_resolver,
                recipient_resolver_config AS recipient_resolver_config,
                created_by_user_id::text  AS created_by_user_id
            FROM tbl_automation_triggers
            WHERE migrated_to_workflow_id IS NULL
            ORDER BY org_id, id
            """
            )
        )
        .mappings()
        .all()
    )

    if not rows:
        logger.info("workflows.absorb_automation no_rows_to_migrate")
        return

    # One-shot lookup of every existing workflow name per org so the
    # collision check inside the loop is O(1) instead of a per-row
    # SELECT.
    existing_names: dict[str, set[str]] = {}
    for org_row in (
        bind.execute(
            sql_text("SELECT DISTINCT org_id::text AS org_id FROM tbl_automation_triggers")
        )
        .mappings()
        .all()
    ):
        org_id = org_row["org_id"]
        names = bind.execute(
            sql_text("SELECT name FROM tbl_workflows WHERE org_id = CAST(:org AS UUID)"),
            {"org": org_id},
        ).all()
        existing_names[org_id] = {n[0] for n in names}

    migrated = 0
    skipped_no_channel = 0

    for row in rows:
        channel = row["channel"]
        node_type = _CHANNEL_TO_NODE_TYPE.get(channel)
        if node_type is None:
            logger.warning(
                "workflows.absorb_automation skip channel_unsupported org=%s automation=%s channel=%s",
                row["org_id"],
                row["id"],
                channel,
            )
            skipped_no_channel += 1
            continue

        source_name = row["name"]
        target_name = source_name
        if target_name in existing_names.get(row["org_id"], set()):
            target_name = f"{source_name}{_COLLISION_SUFFIX}"
            # If STILL colliding (previous run of this migration
            # already placed the mirror), further append the automation
            # id so the row insert cannot conflict on any future unique
            # constraint an operator might add.
            if target_name in existing_names.get(row["org_id"], set()):
                target_name = f"{source_name} (from automation {row['id'][:8]})"

        graph_dict = _build_graph(
            event_type=row["event_type"],
            conditions=dict(row["conditions"] or {}) or None,
            channel_node_type=node_type,
            template_id=row["template_id"],
            recipient_resolver=row["recipient_resolver"],
            recipient_resolver_config=dict(row["recipient_resolver_config"] or {}),
            delay_seconds=int(row["delay_seconds"] or 0),
        )

        target_status = "active" if row["enabled"] else "draft"
        workflow_id = uuid.uuid4()

        bind.execute(
            sql_text(
                """
                INSERT INTO tbl_workflows (
                    id, org_id, name, description, category,
                    status, current_version, re_enrollment_rule,
                    is_marketing, is_system_default,
                    graph, goal_node_id,
                    cost_per_run_cents,
                    enabled_event_types,
                    ab_sibling_id, ab_test_min_runs_per_variant,
                    ab_test_winner_metric,
                    cached_running_count, cached_completed_today_count,
                    created_by_user_id, updated_by_user_id,
                    created_at, updated_at
                ) VALUES (
                    CAST(:id AS UUID),
                    CAST(:org AS UUID),
                    :name, :descr, :cat,
                    CAST(:status AS workflow_status),
                    1,
                    CAST('once' AS workflow_re_enrollment_rule),
                    :is_marketing, false,
                    CAST(:graph AS JSONB),
                    NULL,
                    0,
                    CAST(:events AS TEXT[]),
                    NULL, 50,
                    CAST('goal_conversion' AS ab_winner_metric),
                    0, 0,
                    CAST(:created_by AS UUID),
                    CAST(:created_by AS UUID),
                    now(), now()
                )
                """
            ),
            {
                "id": str(workflow_id),
                "org": row["org_id"],
                "name": target_name,
                "descr": _make_description(
                    source_name=source_name,
                    event_type=row["event_type"],
                    channel=channel,
                ),
                "cat": _MIGRATED_CATEGORY,
                "status": target_status,
                # Marketing vs transactional — automations don't carry
                # this flag; we default to False since the current
                # seeded set (Welcome / Confirmation / Reminders /
                # Invoice notifications / Birthday) is overwhelmingly
                # transactional. Operator can flip via the workflows
                # editor after the cutover.
                "is_marketing": False,
                "graph": json.dumps(graph_dict),
                # asyncpg encodes Python lists directly into TEXT[];
                # passing a Postgres array literal string ('{x,y}')
                # would be rejected as "sized iterable container
                # expected". The Alembic bind here is the app's async
                # engine so we hit the asyncpg path.
                "events": [row["event_type"]],
                "created_by": row["created_by_user_id"],
            },
        )
        bind.execute(
            sql_text(
                """
                INSERT INTO tbl_workflow_versions (
                    id, org_id, workflow_id, version, graph,
                    change_note, created_by_user_id, created_at
                ) VALUES (
                    CAST(:id AS UUID),
                    CAST(:org AS UUID),
                    CAST(:wf AS UUID),
                    1, CAST(:graph AS JSONB),
                    :note,
                    CAST(:created_by AS UUID),
                    now()
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "org": row["org_id"],
                "wf": str(workflow_id),
                "graph": json.dumps(graph_dict),
                "note": (f"Migrated from automation trigger {row['id']} ({row['name']!r})"),
                "created_by": row["created_by_user_id"],
            },
        )
        # Register the target name locally so a second automation with
        # the exact same name inside the same org still gets a unique
        # suffix (defence — the automation triggers table has a
        # functional unique index on (org_id, lower(name)) so this
        # shouldn't fire in practice, but we don't rely on it).
        existing_names.setdefault(row["org_id"], set()).add(target_name)

        # Flip the source: soft-disable + link.  ``enabled=false``
        # gates the automation dispatcher (existing behaviour); the FK
        # is the mapping the redirect resolver + this migration's
        # downgrade both read.
        bind.execute(
            sql_text(
                """
                UPDATE tbl_automation_triggers
                   SET enabled = false,
                       migrated_to_workflow_id = CAST(:wf AS UUID),
                       updated_at = now()
                 WHERE id = CAST(:id AS UUID)
                """
            ),
            {"wf": str(workflow_id), "id": row["id"]},
        )
        migrated += 1

    logger.info(
        "workflows.absorb_automation done migrated=%d skipped_no_channel=%d",
        migrated,
        skipped_no_channel,
    )


def downgrade() -> None:
    """Restore pre-migration state: for every automation with a FK
    set, delete the mirror workflow (cascade takes runs + step_runs +
    versions + event_waits), restore ``enabled=true``, clear the FK."""
    bind = op.get_bind()

    # Collect (source, mirror) pairs so the delete and the update stay
    # in the same order — no risk of an update landing on a
    # freshly-restored FK that we're about to null out anyway.
    pairs = bind.execute(
        sql_text(
            """
            SELECT id::text AS id, migrated_to_workflow_id::text AS wf
              FROM tbl_automation_triggers
             WHERE migrated_to_workflow_id IS NOT NULL
            """
        )
    ).all()

    for source_id, workflow_id in pairs:
        # Explicit cascades to be safe even if a future migration
        # relaxes the ON DELETE on tbl_workflow_versions or friends.
        bind.execute(
            sql_text(
                "DELETE FROM tbl_workflow_step_runs "
                "WHERE run_id IN "
                "  (SELECT id FROM tbl_workflow_runs "
                "     WHERE workflow_id = CAST(:wf AS UUID))"
            ),
            {"wf": workflow_id},
        )
        bind.execute(
            sql_text(
                "DELETE FROM tbl_workflow_event_waits "
                "WHERE run_id IN "
                "  (SELECT id FROM tbl_workflow_runs "
                "     WHERE workflow_id = CAST(:wf AS UUID))"
            ),
            {"wf": workflow_id},
        )
        bind.execute(
            sql_text("DELETE FROM tbl_workflow_runs WHERE workflow_id = CAST(:wf AS UUID)"),
            {"wf": workflow_id},
        )
        bind.execute(
            sql_text("DELETE FROM tbl_workflow_versions WHERE workflow_id = CAST(:wf AS UUID)"),
            {"wf": workflow_id},
        )
        bind.execute(
            sql_text("DELETE FROM tbl_workflows WHERE id = CAST(:wf AS UUID)"),
            {"wf": workflow_id},
        )
        bind.execute(
            sql_text(
                """
                UPDATE tbl_automation_triggers
                   SET enabled = true,
                       migrated_to_workflow_id = NULL,
                       updated_at = now()
                 WHERE id = CAST(:id AS UUID)
                """
            ),
            {"id": source_id},
        )

    logger.info(
        "workflows.absorb_automation.downgrade restored=%d",
        len(pairs),
    )
