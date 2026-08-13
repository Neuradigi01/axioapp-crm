"""Backfill: install the 3 default chat bots on every existing org
(``tasks/chatbot-builder`` Step 15).

New orgs pick up the seeds automatically via
``core.chatbots.seeds.install_default_chatbots`` — this migration
catches every org registered before this track landed.

Alembic's env owns its own async event loop, so ``asyncio.run``
isn't available here (mirrors the ``0144_bf_workflow_seeds`` and
``0187_bf_task_workflows`` constraint). We reach into the runtime
seed literals via a plain import + fan the INSERTs out through the
sync ``bind.execute`` API.

Idempotent — the per-org loop snapshots existing bot names and
skips any seed whose canonical name already exists in that org, so
re-running never duplicates.

Chains after ``0194_org_signed_url_key``.

Revision ID: 0195_bf_chatbot_seeds
Revises:     0194_org_signed_url_key
Create Date: 2026-08-13
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import text as sql_text

from alembic import op

revision: str = "0195_bf_chatbot_seeds"
down_revision: str | None = "0194_org_signed_url_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.chatbots.bf_seeds")

_SEED_NAMES: tuple[str, ...] = (
    "Welcome Bot",
    "Lead Qualification Bot",
    "FAQ Router Bot",
)


def upgrade() -> None:
    """Walk every org, insert the 3 seed bots via raw SQL. Deferred
    import of the runtime seeds so the migration module stays
    loadable in tooling contexts where the app package isn't
    initialised."""
    from src.app.core.chatbots.seeds import _ALL_SEEDS

    bind = op.get_bind()
    orgs = bind.execute(sql_text("SELECT id FROM tbl_organizations")).all()
    if not orgs:
        logger.info("chatbots.bf_seeds no_orgs skipping")
        return

    installed = 0
    skipped = 0

    for (org_id,) in orgs:
        existing_names = {
            (row[0] or "").lower()
            for row in bind.execute(
                sql_text(
                    "SELECT name FROM tbl_chatbots "
                    "WHERE org_id = CAST(:org AS UUID)"
                ),
                {"org": str(org_id)},
            ).all()
        }

        for seed in _ALL_SEEDS:
            name = seed["name"]
            if (name or "").lower() in existing_names:
                skipped += 1
                continue

            bot_id = uuid.uuid4()
            bind.execute(
                sql_text(
                    """
                    INSERT INTO tbl_chatbots (
                        id, org_id, name, description, category, folder_id,
                        status, priority, trigger_config, graph, version_number,
                        created_by_user_id, updated_by_user_id,
                        created_at, updated_at
                    ) VALUES (
                        CAST(:id AS UUID),
                        CAST(:org AS UUID),
                        :name, :descr, :cat, NULL,
                        CAST('draft' AS chatbot_status),
                        :priority,
                        CAST(:trigger AS JSONB),
                        CAST(:graph AS JSONB),
                        1,
                        NULL, NULL,
                        now(), now()
                    )
                    """
                ),
                {
                    "id": str(bot_id),
                    "org": str(org_id),
                    "name": name,
                    "descr": seed["description"],
                    "cat": seed.get("category") or "Seeded",
                    "priority": int(seed.get("priority") or 100),
                    "trigger": json.dumps(seed["trigger_config"]),
                    "graph": json.dumps(seed["graph"]),
                },
            )
            bind.execute(
                sql_text(
                    """
                    INSERT INTO tbl_chatbot_versions (
                        id, org_id, chatbot_id, version_number,
                        graph, trigger_config, change_note,
                        created_by_user_id, created_at
                    ) VALUES (
                        CAST(:id AS UUID),
                        CAST(:org AS UUID),
                        CAST(:bot AS UUID),
                        1,
                        CAST(:graph AS JSONB),
                        CAST(:trigger AS JSONB),
                        'seeded by 0195 backfill',
                        NULL, now()
                    )
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "org": str(org_id),
                    "bot": str(bot_id),
                    "graph": json.dumps(seed["graph"]),
                    "trigger": json.dumps(seed["trigger_config"]),
                },
            )
            existing_names.add((name or "").lower())
            installed += 1

    logger.info(
        "chatbots.bf_seeds done orgs=%d installed=%d skipped=%d",
        len(orgs),
        installed,
        skipped,
    )


def downgrade() -> None:
    """Remove the 3 seeded bots (matched by exact ``name``) across
    every org. Cascade order: step_runs → runs → versions → chatbot rows."""
    bind = op.get_bind()
    names_lower = [n.lower() for n in _SEED_NAMES]

    bind.execute(
        sql_text(
            """
            DELETE FROM tbl_chatbot_step_runs
             WHERE run_id IN (
                SELECT id FROM tbl_chatbot_runs
                 WHERE chatbot_id IN (
                    SELECT id FROM tbl_chatbots
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
            DELETE FROM tbl_chatbot_runs
             WHERE chatbot_id IN (
                SELECT id FROM tbl_chatbots
                 WHERE lower(name) = ANY(:names)
             )
            """
        ),
        {"names": names_lower},
    )
    bind.execute(
        sql_text(
            """
            DELETE FROM tbl_chatbot_versions
             WHERE chatbot_id IN (
                SELECT id FROM tbl_chatbots
                 WHERE lower(name) = ANY(:names)
             )
            """
        ),
        {"names": names_lower},
    )
    bind.execute(
        sql_text("DELETE FROM tbl_chatbots WHERE lower(name) = ANY(:names)"),
        {"names": names_lower},
    )
