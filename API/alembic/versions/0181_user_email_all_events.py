"""fix: broaden the user.email → custom-path rewrite to ALL migrated
workflows (was scoped to ``user.signed_up`` only in 0180).

The workflow module's ``user.email`` resolver crashes with
``'str' object has no attribute 'get'`` when the send-node's
``config.recipient`` is a bare string ("user.email") instead of a
dict — the resolver blindly does ``config.recipient.get("user_id")``.

Migration 0180 only translated User Welcome (event = user.signed_up)
because that was the preset case we discovered first. Ajay's custom
"Leads Assigned/Reassigned" workflow uses the same bare-string
recipient on the ``lead.assigned`` event → same crash → send step
errors instead of firing.

Fix: any Migrated Automation / Preset Workflow whose send node
carries the bare string ``"user.email"`` gets rewritten to
``{"kind": "custom", "path": "user.email"}``. That form pulls the
address from ``payload["user"]["email"]`` at fire time — matches
what the automation module's ``user.email`` resolver did.

The one caveat: if the event's payload doesn't carry a ``user``
sub-dict with an ``email`` (e.g. ``lead.assigned`` publisher decides
to snapshot the assignee under a different key), the send step
skips with ``recipient_not_found`` instead of crashing. That's a
graceful degradation compared to the current error state; operator
can edit the recipient config to pick the right path.

Idempotent: skips nodes already carrying the dict form or a different
recipient shape.

Revision ID: 0181_user_email_all_events
Revises:     0180_fix_user_email_recipient
Create Date: 2026-08-05
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text as sql_text

from alembic import op

revision: str = "0181_user_email_all_events"
down_revision: str | None = "0180_fix_user_email_recipient"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


logger = logging.getLogger("alembic.workflows.user_email_all_events")


_CUSTOM_USER_EMAIL: dict[str, str] = {"kind": "custom", "path": "user.email"}


def _rewrite_forward(graph: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if not isinstance(graph, dict):
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
    if not isinstance(graph, dict):
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
                """
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        logger.info("workflows.user_email_all_events no_candidates skipping")
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
        "workflows.user_email_all_events done candidates=%d rewritten=%d",
        len(rows),
        rewritten,
    )


def upgrade() -> None:
    _run(rewrite=_rewrite_forward)


def downgrade() -> None:
    _run(rewrite=_rewrite_reverse)
