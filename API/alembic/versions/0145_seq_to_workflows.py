"""migrate email_sequences rows into workflows

Step 20 of ``tasks/workflows/`` — converts every active row in
``tbl_email_sequences`` into an equivalent ``tbl_workflows`` row of
type "linear sequence" so the new workflow engine drives sequence
runtime.

Pure-sync raw-SQL implementation (Alembic env owns the loop).

Translation:

  * One sequence → one workflow named ``f"Sequence: {seq.name}"``,
    ``category='Marketing'``, ``is_marketing=True``,
    ``re_enrollment_rule='once'``, ``status='draft'`` (operator
    activates explicitly).
  * Graph: ``[trigger.manual] → [wait(delay_days[i])] → [send.email
    (template_id=step.template_id)]`` for each step, terminating in a
    ``flow_control.goal`` node.

Existing ``tbl_email_sequence_enrollments`` rows are left in place
(read-only retention for one release). New enrollments via
:func:`core.email_sequences.service.enroll` now route through the
workflow engine via the name-based shim lookup.

Idempotent: skips sequences whose canonical workflow name already
exists in the org.

Downgrade: hard-deletes the migrated workflow rows.

Revision ID: 0145_seq_to_workflows
Revises: 0144_bf_workflow_seeds
Create Date: 2026-06-30 15:00:00.000000

"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Sequence, Union

from alembic import op
from sqlalchemy import text as sql_text


revision: str = "0145_seq_to_workflows"
down_revision: Union[str, None] = "0144_bf_workflow_seeds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


logger = logging.getLogger("alembic.workflows.migrate_sequences")


def _build_graph_for_sequence(
    *,
    sequence_name: str,
    steps: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    """Translate a sequence's steps into a linear workflow graph.

    Returns ``(graph_dict, goal_node_id)``. Each step becomes a
    ``[wait(delay_days)] → [send.email(template_id)]`` pair; the
    trigger is the manual trigger so the email_sequences shim can
    ``start_run`` programmatically."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    trigger_id = f"t-{uuid.uuid4().hex[:8]}"
    nodes.append(
        {
            "id": trigger_id,
            "type": "trigger.manual",
            "position": {"x": 240, "y": 80},
            "config": {
                "label": "Manual enrolment",
                "event_type": "sequence.manual_enroll",
                "conditions": None,
            },
        }
    )

    previous = trigger_id
    y_cursor = 200
    for idx, step in enumerate(steps):
        delay_days = int(step.get("delay_days") or 0)
        template_id = step.get("template_id")

        if delay_days > 0:
            wait_id = f"w-{uuid.uuid4().hex[:8]}"
            nodes.append(
                {
                    "id": wait_id,
                    "type": "flow_control.wait",
                    "position": {"x": 240, "y": y_cursor},
                    "config": {
                        "label": f"Wait {delay_days} day(s)",
                        "duration_seconds": delay_days * 86_400,
                    },
                }
            )
            edges.append(
                {
                    "id": f"e-{uuid.uuid4().hex[:8]}",
                    "source": previous,
                    "target": wait_id,
                    "label": None,
                }
            )
            previous = wait_id
            y_cursor += 140

        send_id = f"s-{uuid.uuid4().hex[:8]}"
        send_config: dict[str, Any] = {"label": f"Step {idx + 1}"}
        if template_id is not None:
            send_config["template_id"] = str(template_id)
        nodes.append(
            {
                "id": send_id,
                "type": "send.email",
                "position": {"x": 240, "y": y_cursor},
                "config": send_config,
            }
        )
        edges.append(
            {
                "id": f"e-{uuid.uuid4().hex[:8]}",
                "source": previous,
                "target": send_id,
                "label": None,
            }
        )
        previous = send_id
        y_cursor += 140

    goal_id = f"g-{uuid.uuid4().hex[:8]}"
    nodes.append(
        {
            "id": goal_id,
            "type": "flow_control.goal",
            "position": {"x": 240, "y": y_cursor},
            "config": {"label": "Completed", "name": "Sequence completed"},
        }
    )
    edges.append(
        {
            "id": f"e-{uuid.uuid4().hex[:8]}",
            "source": previous,
            "target": goal_id,
            "label": None,
        }
    )

    return ({"nodes": nodes, "edges": edges}, goal_id)


def upgrade() -> None:
    bind = op.get_bind()

    sequences = bind.execute(
        sql_text(
            "SELECT id, org_id, name FROM tbl_email_sequences "
            "WHERE deleted_at IS NULL ORDER BY org_id, name"
        )
    ).all()

    if not sequences:
        logger.info("workflows.migrate_sequences none_present skipping")
        return

    logger.info(
        "workflows.migrate_sequences starting count=%d", len(sequences)
    )

    migrated = 0
    skipped = 0
    failed = 0

    for seq_row in sequences:
        seq_id, org_id, seq_name = seq_row[0], seq_row[1], seq_row[2]
        canonical = f"Sequence: {seq_name}"

        exists = bind.execute(
            sql_text(
                "SELECT 1 FROM tbl_workflows "
                "WHERE org_id = :org AND name = :name LIMIT 1"
            ),
            {"org": str(org_id), "name": canonical},
        ).first()
        if exists is not None:
            skipped += 1
            continue

        try:
            step_rows = bind.execute(
                sql_text(
                    "SELECT step_order, delay_days, template_id "
                    "FROM tbl_email_sequence_steps "
                    "WHERE sequence_id = :sid "
                    "ORDER BY step_order"
                ),
                {"sid": str(seq_id)},
            ).all()
            steps = [
                {
                    "step_order": r[0],
                    "delay_days": r[1],
                    "template_id": r[2],
                }
                for r in step_rows
            ]
            if not steps:
                skipped += 1
                continue

            graph_dict, goal_node_id = _build_graph_for_sequence(
                sequence_name=seq_name, steps=steps
            )

            workflow_id = uuid.uuid4()
            event_types = ["sequence.manual_enroll"]
            bind.execute(
                sql_text(
                    """
                    INSERT INTO tbl_workflows (
                        id, org_id, name, description, category,
                        status, current_version, re_enrollment_rule,
                        is_marketing, graph, goal_node_id,
                        cost_per_run_cents, enabled_event_types,
                        ab_sibling_id, ab_test_min_runs_per_variant,
                        ab_test_winner_metric,
                        cached_running_count,
                        cached_completed_today_count,
                        created_at, updated_at
                    ) VALUES (
                        CAST(:id AS UUID),
                        CAST(:org AS UUID),
                        :name, :desc, 'Marketing',
                        CAST('draft' AS workflow_status),
                        1,
                        CAST('once' AS workflow_re_enrollment_rule),
                        true, CAST(:graph AS JSONB), :goal,
                        0, CAST(:events AS TEXT[]),
                        NULL, 50,
                        CAST('goal_conversion' AS ab_winner_metric),
                        0, 0,
                        now(), now()
                    )
                    """
                ),
                {
                    "id": str(workflow_id),
                    "org": str(org_id),
                    "name": canonical,
                    "desc": (
                        f"Migrated from email_sequences entry "
                        f"'{seq_name}' on Step 20."
                    ),
                    "graph": json.dumps(graph_dict),
                    "goal": goal_node_id,
                    "events": "{" + ",".join(event_types) + "}",
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
                        'Migrated from email_sequences', NULL, now()
                    )
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "org": str(org_id),
                    "wf": str(workflow_id),
                    "graph": json.dumps(graph_dict),
                },
            )
            migrated += 1
        except Exception:
            logger.exception(
                "workflows.migrate_sequences row_failed seq=%s", seq_id
            )
            failed += 1

    logger.info(
        "workflows.migrate_sequences done migrated=%d skipped=%d failed=%d",
        migrated,
        skipped,
        failed,
    )


def downgrade() -> None:
    op.execute("DELETE FROM tbl_workflows WHERE name LIKE 'Sequence: %'")
