"""fix: translate ``recipient_resolver`` → ``recipient`` on migrated
workflow send nodes.

Second follow-up for ``tasks/workflows-absorb-automation/`` (see
`SMOKE-RESULTS.md`). Companion to ``0178_fix_wf_condition_shape`` —
same class of bug, different key.

Cause: Step-1 migration copied the automation's recipient columns
verbatim onto the workflow send node's config:

    {
      "template_id": "...",
      "recipient_resolver": "contact.email",     # automation key
      "recipient_resolver_config": {}
    }

But the workflow send handler (``core/workflows/actions/send.py``)
reads ``cfg["recipient"]`` — a string (`"contact.email"`) for stock
resolvers or a dict (``{"kind": "custom", "path": ...}``) for
parameterised ones. The mismatched key returns ``None``, so the
send skips with ``skip_reason='recipient_kind_missing'`` and the
email never goes out.

Translation applied per send node:

  * ``recipient_resolver`` (str) + ``recipient_resolver_config`` (empty)
      → ``recipient: <str>``
  * ``recipient_resolver`` (str) + ``recipient_resolver_config`` (dict)
      → ``recipient: {"kind": <str>, **<config>}``
  * Remove ``recipient_resolver`` and ``recipient_resolver_config``.

Idempotent: skips nodes that already carry ``recipient`` or don't
carry ``recipient_resolver`` at all.

Downgrade: reverses the rename (splits string / dict back into the
two-key form) so a rollback restores the migrated-from-automation
shape the Step-1 downgrade expects.

Scope: only workflows whose category is ``'Migrated Automation'``
or ``'Preset Workflow'`` — user-authored workflows never had the
broken key.

Revision ID: 0179_fix_wf_send_recipient
Revises:     0178_fix_wf_condition_shape
Create Date: 2026-08-05
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text as sql_text

from alembic import op

revision: str = "0179_fix_wf_send_recipient"
down_revision: str | None = "0178_fix_wf_condition_shape"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


logger = logging.getLogger("alembic.workflows.fix_send_recipient_key")


def _translate_forward(cfg: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Rename ``recipient_resolver`` (+ optional config) → ``recipient``
    on a send node's config dict. Returns ``(new_cfg, changed)``."""
    if "recipient" in cfg:
        # Already translated on a previous run.
        return cfg, False
    resolver = cfg.get("recipient_resolver")
    if not isinstance(resolver, str) or not resolver:
        return cfg, False

    resolver_config = cfg.get("recipient_resolver_config") or {}
    if isinstance(resolver_config, dict) and resolver_config:
        new_recipient: Any = {"kind": resolver, **resolver_config}
    else:
        new_recipient = resolver

    new_cfg = {
        k: v for k, v in cfg.items() if k not in ("recipient_resolver", "recipient_resolver_config")
    }
    new_cfg["recipient"] = new_recipient
    return new_cfg, True


def _translate_reverse(cfg: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Undo: split ``recipient`` back into ``recipient_resolver`` +
    ``recipient_resolver_config``."""
    if "recipient" not in cfg:
        return cfg, False
    recipient = cfg["recipient"]

    new_cfg = {k: v for k, v in cfg.items() if k != "recipient"}
    if isinstance(recipient, str):
        new_cfg["recipient_resolver"] = recipient
        new_cfg["recipient_resolver_config"] = {}
    elif isinstance(recipient, dict):
        kind = recipient.get("kind")
        if not isinstance(kind, str):
            return cfg, False
        new_cfg["recipient_resolver"] = kind
        new_cfg["recipient_resolver_config"] = {k: v for k, v in recipient.items() if k != "kind"}
    else:
        return cfg, False
    return new_cfg, True


def _rewrite_graph(
    graph: dict[str, Any] | None,
    *,
    translate: Any,
) -> tuple[dict[str, Any], bool]:
    """Walk the graph's send nodes + rewrite each ``config``. Returns
    ``(new_graph, changed_flag)``."""
    if not isinstance(graph, dict):
        return graph or {"nodes": [], "edges": []}, False

    changed = False
    new_nodes: list[dict[str, Any]] = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            new_nodes.append(node)
            continue
        node_type = str(node.get("type") or "")
        if not node_type.startswith("send."):
            new_nodes.append(node)
            continue

        cfg = dict(node.get("config") or {})
        new_cfg, cfg_changed = translate(cfg)
        if cfg_changed:
            changed = True
            new_nodes.append({**node, "config": new_cfg})
        else:
            new_nodes.append(node)

    if not changed:
        return graph, False
    return {**graph, "nodes": new_nodes}, True


def _run(*, translate: Any) -> None:
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
        logger.info("workflows.fix_send_recipient_key no_candidates skipping")
        return

    rewritten = 0
    for row in rows:
        graph = row["graph"]
        if isinstance(graph, str):
            try:
                graph = json.loads(graph)
            except json.JSONDecodeError:
                logger.warning(
                    "workflows.fix_send_recipient_key skip_unparseable_graph workflow=%s",
                    row["id"],
                )
                continue

        new_graph, changed = _rewrite_graph(graph, translate=translate)
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
        "workflows.fix_send_recipient_key done candidates=%d rewritten=%d",
        len(rows),
        rewritten,
    )


def upgrade() -> None:
    _run(translate=_translate_forward)


def downgrade() -> None:
    _run(translate=_translate_reverse)
