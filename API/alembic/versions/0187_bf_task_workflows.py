"""backfill: install the Task Assigned + Task Completed presets on
every existing org.

New orgs pick up the two presets automatically via
``core.workflows.seeds.install_preset_workflows`` — this migration
catches every org registered before this track landed. Mirrors the
``0177_bf_preset_workflows`` pattern (walk every org, insert missing
presets idempotently) and adds a template-seed step first because
the two Task templates don't exist historically in any org.

Pure sync raw-SQL — Alembic's env owns its own async event loop, so
``asyncio.run`` is out (see ``0144_bf_workflow_seeds`` for the same
constraint). Reuses the runtime ``_PRESET_SPECS`` + ``_build_preset_graph``
helpers so drift between the runtime seeder + this backfill can't
happen; only the SQL layer is inlined here.

Idempotent:
  * Templates use ``WHERE NOT EXISTS`` against
    ``(org_id, lower(name), channel)``.
  * Workflows skip when a row with ``lower(name)`` already exists
    in the org.

Safe to re-run.

Downgrade: deletes the seeded workflow + template rows for both
presets (matched by exact ``name`` + ``channel``), plus any workflow
version + run history rows so the FKs stay clean.

Revision ID: 0187_bf_task_workflows
Revises:     0186_bf_tpl_activate_perm
Create Date: 2026-08-13
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import text as sql_text

from alembic import op

revision: str = "0187_bf_task_workflows"
down_revision: str | None = "0186_bf_tpl_activate_perm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


logger = logging.getLogger("alembic.workflows.bf_task_workflows")

_PRESET_NAMES: tuple[str, ...] = ("Task Assigned", "Task Completed")


def upgrade() -> None:
    # Deferred import so Alembic can load this module without eagerly
    # touching the app package — same pattern as 0177.
    from src.app.core.templates.seeds import (
        _TASK_ASSIGNED_BODY,
        _TASK_ASSIGNED_NAME,
        _TASK_ASSIGNED_SUBJECT,
        _TASK_COMPLETED_BODY,
        _TASK_COMPLETED_NAME,
        _TASK_COMPLETED_SUBJECT,
    )
    from src.app.core.workflows.seeds import (
        _PRESET_CATEGORY,
        _PRESET_SPECS,
        _build_preset_graph,
    )

    # Template shape lookups keyed by preset spec name so we insert
    # the right subject/body/variables per row.
    _TEMPLATE_SEED_BY_NAME: dict[str, dict[str, object]] = {
        _TASK_ASSIGNED_NAME: {
            "subject": _TASK_ASSIGNED_SUBJECT,
            "body": _TASK_ASSIGNED_BODY,
            "variables": [
                "assignee.full_name",
                "task.title",
                "task.due_at",
                "task.priority",
                "task.description",
                "org.name",
            ],
        },
        _TASK_COMPLETED_NAME: {
            "subject": _TASK_COMPLETED_SUBJECT,
            "body": _TASK_COMPLETED_BODY,
            "variables": [
                "assignee.full_name",
                "task.title",
                "task.due_at",
                "task.priority",
                "org.name",
            ],
        },
    }

    # Filter the shared _PRESET_SPECS down to just the two entries this
    # backfill installs. Guards against future presets being installed
    # by this migration if _PRESET_SPECS is extended later.
    specs_to_install = [s for s in _PRESET_SPECS if s.name in _PRESET_NAMES]
    if len(specs_to_install) != len(_PRESET_NAMES):
        # Fail loudly rather than silently under-installing — the presets
        # MUST exist in _PRESET_SPECS when this backfill runs.
        raise RuntimeError(
            "0187_bf_task_workflows expected both Task Assigned + Task Completed "
            f"in _PRESET_SPECS; found: {[s.name for s in specs_to_install]}"
        )

    bind = op.get_bind()

    orgs = bind.execute(sql_text("SELECT id FROM tbl_organizations")).all()
    if not orgs:
        logger.info("workflows.bf_task_workflows no_orgs skipping")
        return

    installed_workflows = 0
    installed_templates = 0
    skipped_existing = 0

    for (org_id,) in orgs:
        existing_workflow_names = {
            row[0].lower()
            for row in bind.execute(
                sql_text("SELECT name FROM tbl_workflows WHERE org_id = CAST(:org AS UUID)"),
                {"org": str(org_id)},
            ).all()
        }

        for spec in specs_to_install:
            # ------------------------------------------------------------
            # Template — insert-if-missing.
            # ------------------------------------------------------------
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
                seed = _TEMPLATE_SEED_BY_NAME[spec.name]
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
                        "name": spec.name,
                        "body": seed["body"],
                        "subject": seed["subject"],
                        "variables": json.dumps(seed["variables"]),
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
                        "body": seed["body"],
                        "subject": seed["subject"],
                        "variables": json.dumps(seed["variables"]),
                        "note": f"seeded by 0187 backfill ({spec.name})",
                    },
                )
                installed_templates += 1
            else:
                (template_id,) = template_row

            # ------------------------------------------------------------
            # Workflow — insert-if-missing.
            # ------------------------------------------------------------
            if spec.name.lower() in existing_workflow_names:
                skipped_existing += 1
                continue

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
                        'Initial preset backfill (0187)', NULL, now()
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
            existing_workflow_names.add(spec.name.lower())
            installed_workflows += 1

    logger.info(
        "workflows.bf_task_workflows done orgs=%d workflows_installed=%d "
        "templates_installed=%d skipped_existing=%d",
        len(orgs),
        installed_workflows,
        installed_templates,
        skipped_existing,
    )


def downgrade() -> None:
    """Remove the Task Assigned + Task Completed presets — cleans up
    workflow runs, workflow_step_runs, workflow_versions, workflows,
    template_versions, and templates in FK-safe order.

    Matches rows by exact ``name`` (case-insensitive) so any workflow
    or template a caller manually renamed to avoid the backfill is
    preserved."""
    bind = op.get_bind()
    names_lower = [n.lower() for n in _PRESET_NAMES]

    # 1. Workflow step runs → workflow runs (both cascade would be nice
    #    but not defined; do it explicitly).
    bind.execute(
        sql_text(
            """
            DELETE FROM tbl_workflow_step_runs
             WHERE run_id IN (
                SELECT id FROM tbl_workflow_runs
                 WHERE workflow_id IN (
                    SELECT id FROM tbl_workflows
                     WHERE lower(name) = ANY(:names)
                 )
             )
            """
        ),
        {"names": names_lower},
    )
    bind.execute(
        sql_text(
            """
            DELETE FROM tbl_workflow_runs
             WHERE workflow_id IN (
                SELECT id FROM tbl_workflows
                 WHERE lower(name) = ANY(:names)
             )
            """
        ),
        {"names": names_lower},
    )

    # 2. Workflow versions → workflows.
    bind.execute(
        sql_text(
            """
            DELETE FROM tbl_workflow_versions
             WHERE workflow_id IN (
                SELECT id FROM tbl_workflows
                 WHERE lower(name) = ANY(:names)
             )
            """
        ),
        {"names": names_lower},
    )
    bind.execute(
        sql_text(
            "DELETE FROM tbl_workflows WHERE lower(name) = ANY(:names)"
        ),
        {"names": names_lower},
    )

    # 3. Template versions → templates. Only touch email-channel rows
    #    matching the names, so a same-named WhatsApp template stays.
    bind.execute(
        sql_text(
            """
            DELETE FROM tbl_message_template_versions
             WHERE template_id IN (
                SELECT id FROM tbl_message_templates
                 WHERE lower(name) = ANY(:names)
                   AND channel = CAST('email' AS conversation_channel)
             )
            """
        ),
        {"names": names_lower},
    )
    bind.execute(
        sql_text(
            """
            DELETE FROM tbl_message_templates
             WHERE lower(name) = ANY(:names)
               AND channel = CAST('email' AS conversation_channel)
            """
        ),
        {"names": names_lower},
    )
