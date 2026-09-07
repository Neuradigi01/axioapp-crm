"""backfill: install the Lead Follow-up Scheduled preset workflow +
template on every existing org, and patch the existing Task Assigned
preset workflow to skip lead follow-ups.

New orgs pick both up automatically via
``core.workflows.seeds.install_preset_workflows`` — this migration
catches every org registered before this track landed.

Two-part upgrade:

  1. **Insert Lead Follow-up Scheduled** — mirrors ``0187`` (Task
     Assigned/Task Completed backfill): insert the email template row
     if missing, insert the workflow row if missing. Idempotent on
     ``(org_id, lower(name), channel)`` for the template and
     ``(org_id, lower(name))`` for the workflow.

  2. **Patch Task Assigned trigger conditions** — the pre-existing
     preset fired on every ``task.assigned`` event, so once
     Lead Follow-up Scheduled lands, lead-follow-up tasks would
     produce two emails to the assignee (generic + rich). Adds an
     exclusion so Task Assigned only fires when the task is NOT a
     lead follow-up.

Pure sync raw-SQL — Alembic env owns its own event loop, so
``asyncio.run`` is out (same constraint as ``0144`` / ``0187``).

Downgrade: deletes the seeded Lead Follow-up rows (workflow + version
+ runs + template + template version), and reverts the Task Assigned
trigger's ``config.conditions`` back to ``None`` — but only for
workflows whose current conditions match the exact shape this
migration installed, so an operator who hand-edited the conditions
downstream keeps their edit.

Revision ID: 0220_bf_lead_followup_wf
Revises:     0219_subs_pipeline_stage
Create Date: 2026-09-07
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text as sql_text

from alembic import op

revision: str = "0220_bf_lead_followup_wf"
down_revision: str | None = "0219_subs_pipeline_stage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


logger = logging.getLogger("alembic.workflows.bf_lead_followup")


_TASK_ASSIGNED_NAME_LOWER = "task assigned"
_LEAD_FOLLOW_UP_CONDITIONS: dict[str, Any] = {
    "any": [
        {"op": "neq", "path": "task.related_entity_type", "value": "lead"},
        {"op": "is_null", "path": "task.followup_type"},
    ]
}


def _rewrite_task_assigned_trigger(
    graph: dict[str, Any] | None,
    *,
    new_conditions: dict[str, Any] | None,
) -> tuple[dict[str, Any], bool]:
    """Patch the trigger node's ``config.conditions`` to ``new_conditions``.

    Returns ``(new_graph, changed)``. ``changed=False`` when the graph
    already carries the target conditions (idempotent no-op) or is
    unparseable.
    """
    if not isinstance(graph, dict):
        return graph or {"nodes": [], "edges": []}, False

    changed = False
    new_nodes: list[dict[str, Any]] = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            new_nodes.append(node)
            continue
        node_type = str(node.get("type") or "")
        if not node_type.startswith("trigger"):
            new_nodes.append(node)
            continue

        cfg = dict(node.get("config") or {})
        current = cfg.get("conditions")
        if current == new_conditions:
            new_nodes.append(node)
            continue

        cfg["conditions"] = new_conditions
        changed = True
        new_nodes.append({**node, "config": cfg})

    if not changed:
        return graph, False
    return {**graph, "nodes": new_nodes}, True


def upgrade() -> None:
    # Deferred imports so Alembic can load this module without eagerly
    # touching the app package — matches the 0187 pattern.
    from src.app.core.templates.seeds import (
        _LEAD_FOLLOW_UP_BODY,
        _LEAD_FOLLOW_UP_NAME,
        _LEAD_FOLLOW_UP_SUBJECT,
    )
    from src.app.core.workflows.seeds import (
        _PRESET_CATEGORY,
        _PRESET_SPECS,
        _build_preset_graph,
    )

    spec = next((s for s in _PRESET_SPECS if s.name == _LEAD_FOLLOW_UP_NAME), None)
    if spec is None:
        raise RuntimeError(
            f"0220_bf_lead_followup_wf expected {_LEAD_FOLLOW_UP_NAME!r} in _PRESET_SPECS"
        )

    template_variables = [
        "assignee.full_name",
        "contact.full_name",
        "contact.phone",
        "contact.email",
        "lead.pipeline_stage",
        "task.title",
        "task.due_at",
        "task.followup_type",
        "org.name",
    ]

    bind = op.get_bind()

    orgs = bind.execute(sql_text("SELECT id FROM tbl_organizations")).all()
    if not orgs:
        logger.info("workflows.bf_lead_followup no_orgs skipping")
        return

    installed_workflows = 0
    installed_templates = 0
    patched_task_assigned = 0
    skipped_existing_workflow = 0

    for (org_id,) in orgs:
        # ------------------------------------------------------------------
        # Part 1 — Lead Follow-up Scheduled template + workflow insert.
        # ------------------------------------------------------------------
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
                "name": _LEAD_FOLLOW_UP_NAME.lower(),
                "chan": spec.channel,
            },
        ).one_or_none()

        if template_row is None:
            template_id = uuid.uuid4()
            bind.execute(
                sql_text(
                    """
                    INSERT INTO tbl_message_templates (
                        id, org_id, channel, name, category, language,
                        body_text, subject, variables,
                        internal_status, external_status, current_version,
                        created_at, updated_at
                    ) VALUES (
                        CAST(:id AS UUID),
                        CAST(:org AS UUID),
                        CAST(:chan AS conversation_channel),
                        :name,
                        CAST('transactional' AS template_category),
                        'en',
                        :body,
                        :subject,
                        CAST(:variables AS JSONB),
                        CAST('published' AS template_internal_status),
                        CAST('n_a' AS template_external_status),
                        1,
                        now(), now()
                    )
                    """
                ),
                {
                    "id": str(template_id),
                    "org": str(org_id),
                    "chan": spec.channel,
                    "name": _LEAD_FOLLOW_UP_NAME,
                    "body": _LEAD_FOLLOW_UP_BODY,
                    "subject": _LEAD_FOLLOW_UP_SUBJECT,
                    "variables": json.dumps(template_variables),
                },
            )
            bind.execute(
                sql_text(
                    """
                    INSERT INTO tbl_message_template_versions (
                        id, org_id, template_id, version,
                        body_text, subject, variables,
                        change_note, changed_at
                    ) VALUES (
                        CAST(:id AS UUID),
                        CAST(:org AS UUID),
                        CAST(:tpl AS UUID),
                        1,
                        :body, :subject,
                        CAST(:variables AS JSONB),
                        :note, now()
                    )
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "org": str(org_id),
                    "tpl": str(template_id),
                    "body": _LEAD_FOLLOW_UP_BODY,
                    "subject": _LEAD_FOLLOW_UP_SUBJECT,
                    "variables": json.dumps(template_variables),
                    "note": "seeded by 0220 backfill (Lead Follow-up Scheduled)",
                },
            )
            installed_templates += 1
        else:
            (template_id,) = template_row

        existing_wf_row = bind.execute(
            sql_text(
                """
                SELECT 1
                  FROM tbl_workflows
                 WHERE org_id = CAST(:org AS UUID)
                   AND lower(name) = :name
                 LIMIT 1
                """
            ),
            {"org": str(org_id), "name": _LEAD_FOLLOW_UP_NAME.lower()},
        ).one_or_none()

        if existing_wf_row is None:
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
                    "name": _LEAD_FOLLOW_UP_NAME,
                    "descr": (
                        f"Preset workflow — fires on {spec.event_type}. "
                        f"Sends via {spec.channel}."
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
                        'Initial preset backfill (0220)', NULL, now()
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
            installed_workflows += 1
        else:
            skipped_existing_workflow += 1

        # ------------------------------------------------------------------
        # Part 2 — patch existing "Task Assigned" trigger conditions so
        # it no longer fires for lead follow-ups.
        # ------------------------------------------------------------------
        task_assigned_rows = (
            bind.execute(
                sql_text(
                    """
                    SELECT id::text AS id, graph
                      FROM tbl_workflows
                     WHERE org_id = CAST(:org AS UUID)
                       AND lower(name) = :name
                       AND category = :cat
                    """
                ),
                {
                    "org": str(org_id),
                    "name": _TASK_ASSIGNED_NAME_LOWER,
                    "cat": _PRESET_CATEGORY,
                },
            )
            .mappings()
            .all()
        )

        for row in task_assigned_rows:
            graph = row["graph"]
            if isinstance(graph, str):
                try:
                    graph = json.loads(graph)
                except json.JSONDecodeError:
                    logger.warning(
                        "workflows.bf_lead_followup skip_unparseable_graph workflow=%s",
                        row["id"],
                    )
                    continue

            new_graph, changed = _rewrite_task_assigned_trigger(
                graph, new_conditions=_LEAD_FOLLOW_UP_CONDITIONS
            )
            if not changed:
                continue

            bind.execute(
                sql_text(
                    "UPDATE tbl_workflows "
                    "   SET graph = CAST(:g AS JSONB), updated_at = now() "
                    " WHERE id = CAST(:id AS UUID)"
                ),
                {"id": row["id"], "g": json.dumps(new_graph)},
            )
            bind.execute(
                sql_text(
                    "UPDATE tbl_workflow_versions "
                    "   SET graph = CAST(:g AS JSONB) "
                    " WHERE workflow_id = CAST(:id AS UUID) AND version = 1"
                ),
                {"id": row["id"], "g": json.dumps(new_graph)},
            )
            patched_task_assigned += 1

    logger.info(
        "workflows.bf_lead_followup done orgs=%d workflows_installed=%d "
        "templates_installed=%d task_assigned_patched=%d skipped_existing=%d",
        len(orgs),
        installed_workflows,
        installed_templates,
        patched_task_assigned,
        skipped_existing_workflow,
    )


def downgrade() -> None:
    """Remove the Lead Follow-up Scheduled preset (workflow + template
    + associated runs / versions) and revert Task Assigned trigger
    conditions back to ``None`` — but only for workflows whose current
    conditions match the exact shape ``upgrade()`` installed, so any
    operator hand-edits downstream are preserved."""
    bind = op.get_bind()
    name_lower = "lead follow-up scheduled"

    # ---------- Part 2 reversal: Task Assigned conditions ---------------
    task_assigned_rows = (
        bind.execute(
            sql_text(
                """
                SELECT id::text AS id, graph
                  FROM tbl_workflows
                 WHERE lower(name) = :name
                   AND category = 'Preset Workflow'
                """
            ),
            {"name": _TASK_ASSIGNED_NAME_LOWER},
        )
        .mappings()
        .all()
    )

    for row in task_assigned_rows:
        graph = row["graph"]
        if isinstance(graph, str):
            try:
                graph = json.loads(graph)
            except json.JSONDecodeError:
                continue

        if not isinstance(graph, dict):
            continue

        changed = False
        new_nodes: list[dict[str, Any]] = []
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                new_nodes.append(node)
                continue
            node_type = str(node.get("type") or "")
            if not node_type.startswith("trigger"):
                new_nodes.append(node)
                continue
            cfg = dict(node.get("config") or {})
            if cfg.get("conditions") == _LEAD_FOLLOW_UP_CONDITIONS:
                cfg["conditions"] = None
                new_nodes.append({**node, "config": cfg})
                changed = True
            else:
                new_nodes.append(node)

        if not changed:
            continue

        new_graph = {**graph, "nodes": new_nodes}
        bind.execute(
            sql_text(
                "UPDATE tbl_workflows "
                "   SET graph = CAST(:g AS JSONB), updated_at = now() "
                " WHERE id = CAST(:id AS UUID)"
            ),
            {"id": row["id"], "g": json.dumps(new_graph)},
        )
        bind.execute(
            sql_text(
                "UPDATE tbl_workflow_versions "
                "   SET graph = CAST(:g AS JSONB) "
                " WHERE workflow_id = CAST(:id AS UUID) AND version = 1"
            ),
            {"id": row["id"], "g": json.dumps(new_graph)},
        )

    # ---------- Part 1 reversal: delete Lead Follow-up preset ----------
    bind.execute(
        sql_text(
            """
            DELETE FROM tbl_workflow_step_runs
             WHERE run_id IN (
                SELECT id FROM tbl_workflow_runs
                 WHERE workflow_id IN (
                    SELECT id FROM tbl_workflows
                     WHERE lower(name) = :name
                 )
             )
            """
        ),
        {"name": name_lower},
    )
    bind.execute(
        sql_text(
            """
            DELETE FROM tbl_workflow_runs
             WHERE workflow_id IN (
                SELECT id FROM tbl_workflows
                 WHERE lower(name) = :name
             )
            """
        ),
        {"name": name_lower},
    )
    bind.execute(
        sql_text(
            """
            DELETE FROM tbl_workflow_versions
             WHERE workflow_id IN (
                SELECT id FROM tbl_workflows
                 WHERE lower(name) = :name
             )
            """
        ),
        {"name": name_lower},
    )
    bind.execute(
        sql_text("DELETE FROM tbl_workflows WHERE lower(name) = :name"),
        {"name": name_lower},
    )
    bind.execute(
        sql_text(
            """
            DELETE FROM tbl_message_template_versions
             WHERE template_id IN (
                SELECT id FROM tbl_message_templates
                 WHERE lower(name) = :name
                   AND channel = CAST('email' AS conversation_channel)
             )
            """
        ),
        {"name": name_lower},
    )
    bind.execute(
        sql_text(
            """
            DELETE FROM tbl_message_templates
             WHERE lower(name) = :name
               AND channel = CAST('email' AS conversation_channel)
            """
        ),
        {"name": name_lower},
    )
