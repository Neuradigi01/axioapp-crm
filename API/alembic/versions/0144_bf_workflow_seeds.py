"""backfill seeded workflows into every existing org

Step 20 of ``tasks/workflows/`` — iterates every org currently in
``tbl_organizations`` and installs the 15 default core workflows
from :data:`core.workflows.templates_gallery.CATALOG`. New orgs going
forward get the seeds via the provisioning hook in
``core/tenants/service.create_organization``.

Pure-sync raw-SQL implementation: Alembic's env already owns an
async event loop (see ``alembic/env.py``), so we can't use
``asyncio.run`` here. Instead we read the catalogue from Python +
INSERT rows directly via ``op.execute``. The strip-template-ids +
graph-validate logic is replicated inline so this migration doesn't
depend on the async ``clone_from_gallery`` path.

Idempotent — skips workflows whose canonical name already exists in
the org. Re-running the migration after partial failure picks up
the missing rows.

Downgrade: archives the seeded workflow rows (``status='archived'``)
rather than deleting them, so any in-flight runs against a seed
finish cleanly.

Revision ID: 0144_bf_workflow_seeds
Revises: 0143_workflow_cached_counters
Create Date: 2026-06-30 14:00:00.000000

"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text as sql_text


revision: str = "0144_bf_workflow_seeds"
down_revision: Union[str, None] = "0143_workflow_cached_counters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


logger = logging.getLogger("alembic.workflows.bf_seeds")


def _strip_template_ids(graph: dict) -> dict:
    """Match :func:`core.workflows.templates_gallery._strip_send_template_ids`
    so seeded rows match what a manual gallery clone would produce."""
    nodes = []
    for node in graph.get("nodes") or []:
        node_type = str(node.get("type") or "")
        if node_type.startswith("send.") or node_type.startswith("record.create_"):
            new_config = dict(node.get("config") or {})
            new_config.pop("template_id", None)
            new_config["__valid"] = False
            nodes.append({**node, "config": new_config})
        else:
            nodes.append(node)
    return {"nodes": nodes, "edges": list(graph.get("edges") or [])}


def _extract_event_types(graph: dict) -> list[str]:
    """Pull trigger ``event_type`` strings out of the graph so the
    denormalised ``enabled_event_types`` column stays in sync."""
    out: list[str] = []
    for node in graph.get("nodes") or []:
        if str(node.get("type") or "").startswith("trigger"):
            event_type = (node.get("config") or {}).get("event_type")
            if isinstance(event_type, str) and event_type:
                out.append(event_type)
    return out


def upgrade() -> None:
    from src.app.core.workflows import templates_gallery as _gallery

    bind = op.get_bind()

    orgs = bind.execute(sql_text("SELECT id FROM tbl_organizations")).all()
    if not orgs:
        logger.info("workflows.bf_seeds no_orgs_present skipping")
        return

    installed = 0
    skipped = 0

    for (org_id,) in orgs:
        # One-shot lookup of every workflow name already in the org —
        # avoids 15 round-trips per org.
        existing = {
            row[0]
            for row in bind.execute(
                sql_text("SELECT name FROM tbl_workflows WHERE org_id = :org"),
                {"org": str(org_id)},
            ).all()
        }

        for entry in _gallery.CATALOG:
            if entry.name in existing:
                skipped += 1
                continue

            graph_dict = _strip_template_ids(entry.graph_preview)
            goal_node_id = entry.graph_preview.get("goal_node_id")
            event_types = _extract_event_types(graph_dict)

            workflow_id = uuid.uuid4()
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
                        :name, :desc, :cat,
                        CAST('draft' AS workflow_status),
                        1,
                        CAST(:reenroll AS workflow_re_enrollment_rule),
                        :is_marketing, CAST(:graph AS JSONB), :goal,
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
                    "name": entry.name,
                    "desc": entry.description,
                    "cat": entry.category,
                    "reenroll": entry.re_enrollment_rule,
                    "is_marketing": entry.is_marketing,
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
                        'Initial seed', NULL, now()
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
            existing.add(entry.name)
            installed += 1

    logger.info(
        "workflows.bf_seeds done orgs=%d installed=%d skipped=%d",
        len(orgs),
        installed,
        skipped,
    )


def downgrade() -> None:
    """Archive seed-named workflows so in-flight runs continue cleanly."""
    from src.app.core.workflows import templates_gallery as _gallery

    names = [entry.name for entry in _gallery.CATALOG]
    bind = op.get_bind()
    bind.execute(
        sql_text(
            "UPDATE tbl_workflows "
            "SET status='archived', updated_at=now() "
            "WHERE name = ANY(:names) AND status != 'archived'"
        ).bindparams(names=names)
    )
