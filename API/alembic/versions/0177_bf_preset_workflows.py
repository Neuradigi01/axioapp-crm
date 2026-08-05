"""backfill: install the ten preset workflows on every existing org.

Step 2 of ``tasks/workflows-absorb-automation/`` — belt-and-braces for
the org-creation seed swap. Step 1's data migration mirrored every
existing automation into a workflow, but an org that had DELETED one
of the presets before the cutover (rare — the automation UI supports
disable, not delete, but a direct DB write or a support-tool script
could have removed rows) would end up missing that preset workflow on
this cutover.

This migration walks every org and installs any preset workflow that
is missing AND whose backing template already exists in the org. The
template check is what makes this safe: automations that seeded a
template historically would still leave that template behind even
if the automation itself was deleted, so we install the workflow
using the pre-existing template_id. Orgs that never had the automation
(and therefore never had the template) get nothing — respects operator
intent.

Reuses the same ``_PRESET_SPECS`` + ``_build_preset_graph`` helpers
that ``core.workflows.seeds.install_preset_workflows`` uses at
runtime, so drift between the runtime path and the backfill can't
happen.

Idempotency: skips presets whose lower(name) is already present as a
workflow in the org. Safe to re-run.

Downgrade: deletes every workflow (+ versions) whose category is
``'Preset Workflow'`` — the sentinel set by both the runtime seeder
and this backfill. Cleanly reverses both the backfill AND any preset
workflow installed by ``create_organization`` after Step 2 shipped.
Step 1's migrated automations use category ``'Migrated Automation'``
and are unaffected.

Revision ID: 0177_bf_preset_workflows
Revises:     0176_bf_autos_to_workflows
Create Date: 2026-08-05
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import text as sql_text

from alembic import op

revision: str = "0177_bf_preset_workflows"
down_revision: str | None = "0176_bf_autos_to_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


logger = logging.getLogger("alembic.workflows.bf_preset_workflows")


def upgrade() -> None:
    # Import runtime helpers so the spec list + graph builder never
    # drift between the runtime seeder + this backfill. Deferred import
    # so Alembic can load this module without eagerly hitting the app
    # package (matches the pattern in 0144_bf_workflow_seeds.py).
    from src.app.core.workflows.seeds import (
        _PRESET_CATEGORY,
        _PRESET_SPECS,
        _build_preset_graph,
    )

    bind = op.get_bind()

    orgs = bind.execute(sql_text("SELECT id FROM tbl_organizations")).all()
    if not orgs:
        logger.info("workflows.bf_preset_workflows no_orgs skipping")
        return

    installed = 0
    skipped_existing = 0
    skipped_no_template = 0

    for (org_id,) in orgs:
        existing_names = {
            row[0].lower()
            for row in bind.execute(
                sql_text("SELECT name FROM tbl_workflows WHERE org_id = CAST(:org AS UUID)"),
                {"org": str(org_id)},
            ).all()
        }

        for spec in _PRESET_SPECS:
            if spec.name.lower() in existing_names:
                skipped_existing += 1
                continue

            # Look up the matching template by (name, channel). Every
            # org that had the automation historically also seeded the
            # template — if this returns NULL the org never had the
            # automation, so we skip (respect operator intent).
            template_row = bind.execute(
                sql_text(
                    """
                    SELECT id
                      FROM tbl_message_templates
                     WHERE org_id = CAST(:org AS UUID)
                       AND lower(name) = :name
                       AND channel = CAST(:chan AS conversation_channel)
                     LIMIT 1
                    """
                ),
                {
                    "org": str(org_id),
                    "name": spec.name.lower(),
                    "chan": spec.channel,
                },
            ).one_or_none()

            if template_row is None:
                skipped_no_template += 1
                logger.info(
                    "workflows.bf_preset_workflows skip_no_template org=%s name=%s",
                    org_id,
                    spec.name,
                )
                continue

            (template_id,) = template_row
            graph_dict = _build_preset_graph(spec, template_id=str(template_id))
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
                        CAST('active' AS workflow_status),
                        1,
                        CAST('once' AS workflow_re_enrollment_rule),
                        false, false,
                        CAST(:graph AS JSONB),
                        NULL,
                        0,
                        CAST(:events AS TEXT[]),
                        NULL, 50,
                        CAST('goal_conversion' AS ab_winner_metric),
                        0, 0,
                        NULL, NULL,
                        now(), now()
                    )
                    """
                ),
                {
                    "id": str(workflow_id),
                    "org": str(org_id),
                    "name": spec.name,
                    "descr": (
                        f"Preset workflow — fires on {spec.event_type}. Sends via {spec.channel}."
                    ),
                    "cat": _PRESET_CATEGORY,
                    "graph": json.dumps(graph_dict),
                    "events": [spec.event_type],
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
                        'Initial preset backfill', NULL, now()
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
            existing_names.add(spec.name.lower())
            installed += 1

    logger.info(
        "workflows.bf_preset_workflows done orgs=%d installed=%d "
        "skipped_existing=%d skipped_no_template=%d",
        len(orgs),
        installed,
        skipped_existing,
        skipped_no_template,
    )


def downgrade() -> None:
    """Remove every workflow whose category is ``'Preset Workflow'`` —
    the sentinel set by both this backfill AND the runtime
    ``install_preset_workflows`` seeder. Also drops the accompanying
    tbl_workflow_versions rows. Step 1's migrated automations
    (category = ``'Migrated Automation'``) are unaffected."""
    from src.app.core.workflows.seeds import _PRESET_CATEGORY

    bind = op.get_bind()

    # Cascade the associated run history first — a preset workflow that
    # has already fired since Step 2 shipped would leave dangling FKs
    # otherwise. WorkflowRun → WorkflowStepRun cascade via ONDELETE, but
    # WorkflowRun itself does not cascade off tbl_workflows so we clean
    # explicitly.
    bind.execute(
        sql_text(
            """
            DELETE FROM tbl_workflow_step_runs
             WHERE run_id IN (
                SELECT id FROM tbl_workflow_runs
                 WHERE workflow_id IN (
                    SELECT id FROM tbl_workflows WHERE category = :cat
                 )
             )
            """
        ),
        {"cat": _PRESET_CATEGORY},
    )
    bind.execute(
        sql_text(
            """
            DELETE FROM tbl_workflow_event_waits
             WHERE run_id IN (
                SELECT id FROM tbl_workflow_runs
                 WHERE workflow_id IN (
                    SELECT id FROM tbl_workflows WHERE category = :cat
                 )
             )
            """
        ),
        {"cat": _PRESET_CATEGORY},
    )
    bind.execute(
        sql_text(
            "DELETE FROM tbl_workflow_runs WHERE workflow_id IN "
            "  (SELECT id FROM tbl_workflows WHERE category = :cat)"
        ),
        {"cat": _PRESET_CATEGORY},
    )
    bind.execute(
        sql_text(
            "DELETE FROM tbl_workflow_versions WHERE workflow_id IN "
            "  (SELECT id FROM tbl_workflows WHERE category = :cat)"
        ),
        {"cat": _PRESET_CATEGORY},
    )
    bind.execute(
        sql_text("DELETE FROM tbl_workflows WHERE category = :cat"),
        {"cat": _PRESET_CATEGORY},
    )
