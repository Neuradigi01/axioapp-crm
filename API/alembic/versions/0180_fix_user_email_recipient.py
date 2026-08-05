"""fix: change migrated ``user.signed_up`` workflow send-node recipient
from bare ``"user.email"`` to ``{"kind": "custom", "path": "user.email"}``.

Third follow-up for ``tasks/workflows-absorb-automation/``. The
workflow module's ``user.email`` resolver looks up a user by ID via
``node.config.recipient.user_id`` or falls back to
``workflow.created_by_user_id``. For a signup event neither is
populated — the resolver returns None + the send skips with
``recipient_not_found``. The automation module's ``user.email``
resolver reads ``payload["user"]["email"]`` directly; the workflow
equivalent is the ``custom`` resolver against that same path.

Applies only to send nodes on workflows whose trigger event is
``user.signed_up`` (i.e. the "User Welcome" preset + any custom
migrated automation subscribed to the same event) AND whose current
``config.recipient`` is the bare string ``"user.email"``. Idempotent
+ narrowly scoped so it can't touch operator-authored recipients.

Downgrade: reverses the change — folds the custom-path dict back to
the bare string.

Revision ID: 0180_fix_user_email_recipient
Revises:     0179_fix_wf_send_recipient
Create Date: 2026-08-05
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text as sql_text

from alembic import op

revision: str = "0180_fix_user_email_recipient"
down_revision: str | None = "0179_fix_wf_send_recipient"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


logger = logging.getLogger("alembic.workflows.fix_user_email_recipient")


_CUSTOM_USER_EMAIL: dict[str, str] = {"kind": "custom", "path": "user.email"}


def _rewrite_forward(graph: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """If the workflow trigger is ``user.signed_up`` and any send
    node's recipient is the bare string ``"user.email"``, rewrite to
    the custom-path dict form."""
    if not isinstance(graph, dict):
        return graph, False

    # Only touch workflows whose trigger listens on user.signed_up.
    trigger = None
    for n in graph.get("nodes") or []:
        if isinstance(n, dict) and str(n.get("type") or "").startswith("trigger"):
            trigger = n
            break
    if trigger is None:
        return graph, False
    if (trigger.get("config") or {}).get("event_type") != "user.signed_up":
        return graph, False

    changed = False
    new_nodes: list[dict[str, Any]] = []
    for n in graph.get("nodes") or []:
        if not isinstance(n, dict):
            new_nodes.append(n)
            continue
        if not str(n.get("type") or "").startswith("send."):
            new_nodes.append(n)
            continue
        cfg = dict(n.get("config") or {})
        if cfg.get("recipient") == "user.email":
            cfg["recipient"] = dict(_CUSTOM_USER_EMAIL)
            changed = True
            new_nodes.append({**n, "config": cfg})
        else:
            new_nodes.append(n)
    if not changed:
        return graph, False
    return {**graph, "nodes": new_nodes}, True


def _rewrite_reverse(graph: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Fold the custom-path back to ``"user.email"``."""
    if not isinstance(graph, dict):
        return graph, False

    trigger = None
    for n in graph.get("nodes") or []:
        if isinstance(n, dict) and str(n.get("type") or "").startswith("trigger"):
            trigger = n
            break
    if trigger is None:
        return graph, False
    if (trigger.get("config") or {}).get("event_type") != "user.signed_up":
        return graph, False

    changed = False
    new_nodes: list[dict[str, Any]] = []
    for n in graph.get("nodes") or []:
        if not isinstance(n, dict):
            new_nodes.append(n)
            continue
        if not str(n.get("type") or "").startswith("send."):
            new_nodes.append(n)
            continue
        cfg = dict(n.get("config") or {})
        recipient = cfg.get("recipient")
        if isinstance(recipient, dict) and recipient == _CUSTOM_USER_EMAIL:
            cfg["recipient"] = "user.email"
            changed = True
            new_nodes.append({**n, "config": cfg})
        else:
            new_nodes.append(n)
    if not changed:
        return graph, False
    return {**graph, "nodes": new_nodes}, True


def _run(*, rewrite: Any) -> None:
    bind = op.get_bind()
    rows = (
        bind.execute(
            sql_text(
                """
                SELECT id::text AS id, graph
                  FROM tbl_workflows
                 WHERE category IN ('Migrated Automation', 'Preset Workflow')
                   AND 'user.signed_up' = ANY(enabled_event_types)
                """
            )
        )
        .mappings()
        .all()
    )

    if not rows:
        logger.info("workflows.fix_user_email_recipient no_candidates skipping")
        return

    rewritten = 0
    for row in rows:
        graph = row["graph"]
        if isinstance(graph, str):
            try:
                graph = json.loads(graph)
            except json.JSONDecodeError:
                continue
        new_graph, changed = rewrite(graph)
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
        rewritten += 1

    logger.info(
        "workflows.fix_user_email_recipient done candidates=%d rewritten=%d",
        len(rows),
        rewritten,
    )


def upgrade() -> None:
    _run(rewrite=_rewrite_forward)


def downgrade() -> None:
    _run(rewrite=_rewrite_reverse)
