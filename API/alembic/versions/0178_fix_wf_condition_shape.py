"""fix: translate migrated workflow trigger conditions to the workflow
condition-AST shape.

Post-cutover follow-up for ``tasks/workflows-absorb-automation/`` (see
`SMOKE-RESULTS.md`). The Step-1 data migration copied automation
``conditions`` JSONB verbatim onto the mirror workflow's trigger node.
But the two modules use different condition-AST shapes:

    Automation (older, ``core/automation/conditions.py``):
        {"op": "ne",  "field": "source", "value": "bulk_import"}
        ops: ne, regex, not_exists

    Workflow (newer, ``core/events/conditions.py``):
        {"op": "neq", "path":  "source", "value": "bulk_import"}
        ops: neq, matches, {"not": {"op": "exists", …}}

Result of the mismatch: ``events.conditions.evaluate_safe`` rejects
the leaf ("missing 'path'") + returns False for every published event.
The workflow subscriber never enrols anyone → zero
``tbl_workflow_runs`` for every migrated automation → no Welcome /
Lead Confirmation / Reminder emails go out.

This migration walks every workflow whose category marks it as a
migration or preset (``'Migrated Automation'`` / ``'Preset Workflow'``)
and recursively rewrites its trigger-node conditions:

  * ``field`` → ``path``
  * ``ne`` → ``neq``
  * ``regex`` → ``matches``
  * ``not_exists`` → wrap in ``{"not": {"op": "exists", "path": …}}``

Both ``tbl_workflows.graph`` and the v=1 row in
``tbl_workflow_versions`` are updated so the operator's next
"revert to v1" via the version history doesn't re-introduce the
broken shape.

Idempotent: leaves already-translated conditions untouched (checks for
``field`` / old ops before rewriting).

Downgrade: reverses the translation (``path``→``field``, ``neq``→``ne``,
etc.) so a rollback restores the original migrated shape (which the
automation dispatcher would still understand — the mirror workflows
would be broken, but the FK-restored automations would fire again).

Revision ID: 0178_fix_wf_condition_shape
Revises:     0177_bf_preset_workflows
Create Date: 2026-08-05
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text as sql_text

from alembic import op

revision: str = "0178_fix_wf_condition_shape"
down_revision: str | None = "0177_bf_preset_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


logger = logging.getLogger("alembic.workflows.fix_condition_shape")


# Automation-format op names → workflow-format op names.
_OP_FORWARD: dict[str, str] = {
    "ne": "neq",
    "regex": "matches",
}
_OP_REVERSE: dict[str, str] = {v: k for k, v in _OP_FORWARD.items()}


def _translate_forward(node: Any) -> Any:
    """Recursively rewrite an automation-shape condition to the
    workflow shape. Handles compound (all/any/not) + leaf + already-
    translated nodes (idempotent)."""
    if not isinstance(node, dict):
        return node

    # Compound gates — recurse into children unchanged (they're the
    # same key across both shapes).
    for gate in ("all", "any"):
        if gate in node:
            children = node[gate]
            if isinstance(children, list):
                return {gate: [_translate_forward(c) for c in children]}
            return node
    if "not" in node:
        return {"not": _translate_forward(node["not"])}

    # Leaf.
    op_str = node.get("op")
    if not isinstance(op_str, str):
        return node

    # Special-case: not_exists = compound `{not: {op: exists, path: …}}`.
    if op_str == "not_exists":
        selector = node.get("field") or node.get("path")
        if not isinstance(selector, str):
            return node
        return {"not": {"op": "exists", "path": selector}}

    out: dict[str, Any] = {}
    for k, v in node.items():
        if k == "field":
            out["path"] = v
        elif k == "op":
            out["op"] = _OP_FORWARD.get(v, v)
        else:
            out[k] = v
    # If the caller already had ``path`` (idempotent re-run), we
    # merge — ``path`` wins over an accidental ``field`` key.
    if "field" in node and "path" not in out:
        out["path"] = node["field"]
    return out


def _translate_reverse(node: Any) -> Any:
    """Downgrade: workflow shape → automation shape."""
    if not isinstance(node, dict):
        return node
    for gate in ("all", "any"):
        if gate in node:
            children = node[gate]
            if isinstance(children, list):
                return {gate: [_translate_reverse(c) for c in children]}
            return node
    if "not" in node:
        inner = node["not"]
        # Fold the compound not-exists back to the leaf form.
        if (
            isinstance(inner, dict)
            and inner.get("op") == "exists"
            and isinstance(inner.get("path"), str)
        ):
            return {"op": "not_exists", "field": inner["path"]}
        return {"not": _translate_reverse(inner)}
    op_str = node.get("op")
    if not isinstance(op_str, str):
        return node
    out: dict[str, Any] = {}
    for k, v in node.items():
        if k == "path":
            out["field"] = v
        elif k == "op":
            out["op"] = _OP_REVERSE.get(v, v)
        else:
            out[k] = v
    return out


def _rewrite_graph(
    graph: dict[str, Any] | None,
    *,
    translate: Any,
) -> tuple[dict[str, Any], bool]:
    """Walk the graph's trigger nodes + rewrite each ``config.conditions``.
    Returns (new_graph, changed_flag)."""
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
        original = cfg.get("conditions")
        if not isinstance(original, dict) or not original:
            new_nodes.append(node)
            continue

        translated = translate(original)
        if translated != original:
            cfg["conditions"] = translated
            changed = True
        new_node = {**node, "config": cfg}
        new_nodes.append(new_node)

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
        logger.info("workflows.fix_condition_shape no_migrated_or_preset_rows skipping")
        return

    rewritten = 0
    for row in rows:
        graph = row["graph"]
        # asyncpg / psycopg return JSONB either as parsed dict or as str
        # depending on driver + Alembic env; normalise defensively.
        if isinstance(graph, str):
            try:
                graph = json.loads(graph)
            except json.JSONDecodeError:
                logger.warning(
                    "workflows.fix_condition_shape skip_unparseable_graph workflow=%s",
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
        # Keep v=1 versions in sync so a "revert to v1" doesn't
        # re-introduce the broken shape.
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
        "workflows.fix_condition_shape done candidates=%d rewritten=%d",
        len(rows),
        rewritten,
    )


def upgrade() -> None:
    _run(translate=_translate_forward)


def downgrade() -> None:
    _run(translate=_translate_reverse)
