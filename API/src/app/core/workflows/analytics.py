"""Per-workflow analytics computation.

Step 19 of ``tasks/workflows/`` — orchestrates the DAL aggregate
queries (:mod:`core.workflows.data_access`) into the shape the
dashboard renders. No transactions here: this module reads only.

The shape returned by :func:`compute_workflow_metrics` mirrors the
``WorkflowAnalyticsResponse`` schema:

  * ``totals`` — headline KPIs (enrolled / completed / goal_reached
    / errored / running / conversion_rate / avg_completion_seconds /
    estimated_cost_cents).
  * ``funnel`` — ordered list of per-node counts. Order is sourced
    from the workflow graph (BFS from trigger), so the dashboard
    can render the funnel without re-walking the JSONB.
  * ``skip_reasons`` — ``{node_id: {reason: count}}`` for the
    drawer.
  * ``send_metrics`` — per-channel rollup. The "channel" is derived
    from the node's ``type`` (``send.email`` → email, etc.) so we
    can group across many nodes of the same channel.

Per the layered convention (manager spec 2026-06-25):

  * This module does NOT touch transactions.
  * Reads from :mod:`core.workflows.data_access`; no direct ORM SQL.
  * The Step-19 router calls :func:`compute_workflow_metrics` after
    resolving + permission-checking the workflow.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.workflows import data_access as _da
from src.app.core.workflows.models import Workflow


# Send-node prefix → channel label. The send-action registry
# (``actions/send.py``) registers ``send.email`` / ``send.whatsapp`` /
# ``send.sms`` / ``send.facebook`` / ``send.instagram`` / ``send.push``
# / ``send.slack``. We strip the ``send.`` prefix here so the rollup
# groups by friendly channel name.
_SEND_NODE_PREFIX = "send."


def _node_label(node: dict[str, Any], fallback: str) -> str:
    """Best-effort human label for a graph node — used in the funnel
    + send rollup. Falls back to the node id when no label is set
    so the dashboard always renders something."""
    config = node.get("config") or {}
    for key in ("label", "name", "title"):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def _graph_node_order(workflow: Workflow) -> list[str]:
    """BFS the workflow graph from the trigger node to fix funnel
    ordering. Disconnected nodes get appended at the end so the
    funnel never silently drops them."""
    graph = workflow.graph or {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []

    nodes_by_id = {n["id"]: n for n in nodes if isinstance(n, dict) and "id" in n}
    if not nodes_by_id:
        return []

    out_edges: dict[str, list[str]] = {}
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src = edge.get("source")
        tgt = edge.get("target")
        if isinstance(src, str) and isinstance(tgt, str):
            out_edges.setdefault(src, []).append(tgt)

    trigger_id: str | None = None
    for node_id, node in nodes_by_id.items():
        if str(node.get("type", "")).startswith("trigger"):
            trigger_id = node_id
            break

    visited: list[str] = []
    seen: set[str] = set()
    queue: list[str] = [trigger_id] if trigger_id else []
    while queue:
        current = queue.pop(0)
        if current in seen or current not in nodes_by_id:
            continue
        seen.add(current)
        visited.append(current)
        queue.extend(out_edges.get(current, []))

    for node_id in nodes_by_id:
        if node_id not in seen:
            visited.append(node_id)
    return visited


async def compute_workflow_metrics(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow: Workflow,
    since: datetime,
    until: datetime,
) -> dict[str, Any]:
    """Headline KPIs + funnel + skip-reason breakdown + send rollup.

    Returns the dict the ``WorkflowAnalyticsResponse`` schema will
    validate. ROI math:
        ``estimated_cost_cents = enrolled * workflow.cost_per_run_cents``.
    """
    totals = await _da.aggregate_runs_in_window(
        session,
        org_id=org_id,
        workflow_id=workflow.id,
        since=since,
        until=until,
    )
    funnel_rows = await _da.aggregate_funnel(
        session,
        org_id=org_id,
        workflow_id=workflow.id,
        since=since,
        until=until,
    )
    skip_rows = await _da.aggregate_skip_reasons(
        session,
        org_id=org_id,
        workflow_id=workflow.id,
        since=since,
        until=until,
    )
    send_rows = await _da.aggregate_send_metrics(
        session,
        org_id=org_id,
        workflow_id=workflow.id,
        since=since,
        until=until,
    )

    enrolled = totals["enrolled"] or 0
    goal_reached = totals["goal_reached"] or 0
    conversion_rate = (goal_reached / enrolled) if enrolled else 0.0
    cost_cents = enrolled * (workflow.cost_per_run_cents or 0)

    # Order the funnel by graph BFS so the dashboard renders the
    # natural flow instead of a hash-keyed jumble.
    ordering = _graph_node_order(workflow)
    nodes_by_id = workflow.graph_nodes_by_id
    funnel_by_node = {row["node_id"]: row for row in funnel_rows}
    funnel_ordered: list[dict[str, Any]] = []
    for node_id in ordering:
        node = nodes_by_id.get(node_id) or {}
        row = funnel_by_node.get(
            node_id,
            {
                "node_id": node_id,
                "total": 0,
                "completed_count": 0,
                "skipped_count": 0,
                "errored_count": 0,
            },
        )
        funnel_ordered.append(
            {
                **row,
                "label": _node_label(node, node_id),
                "node_type": node.get("type") or "unknown",
            }
        )
    # Step_runs from defunct nodes (deleted from graph but still
    # have history) get appended last.
    for node_id, row in funnel_by_node.items():
        if node_id not in nodes_by_id:
            funnel_ordered.append(
                {
                    **row,
                    "label": f"(removed: {node_id[:8]}…)",
                    "node_type": "unknown",
                }
            )

    # Send rollup — group node_ids by channel.
    send_by_channel: dict[str, dict[str, int]] = {}
    for row in send_rows:
        node = nodes_by_id.get(row["node_id"])
        if not node:
            continue
        node_type = str(node.get("type") or "")
        if not node_type.startswith(_SEND_NODE_PREFIX):
            continue
        channel = node_type[len(_SEND_NODE_PREFIX) :] or "unknown"
        bucket = send_by_channel.setdefault(
            channel,
            {"total": 0, "delivered": 0, "skipped": 0, "errored": 0},
        )
        count = int(row["count"])
        bucket["total"] += count
        if row["status"] == "completed":
            bucket["delivered"] += count
        elif row["status"] == "skipped":
            bucket["skipped"] += count
        elif row["status"] == "errored":
            bucket["errored"] += count
    send_metrics = []
    for channel, counts in send_by_channel.items():
        delivery_rate = (
            (counts["delivered"] / counts["total"]) if counts["total"] else 0.0
        )
        send_metrics.append(
            {
                "channel": channel,
                **counts,
                "delivery_rate": delivery_rate,
            }
        )
    send_metrics.sort(key=lambda r: r["total"], reverse=True)

    return {
        "workflow_id": workflow.id,
        "window": {"since": since, "until": until},
        "totals": {
            **totals,
            "conversion_rate": conversion_rate,
            "estimated_cost_cents": cost_cents,
        },
        "funnel": funnel_ordered,
        "skip_reasons": skip_rows,
        "send_metrics": send_metrics,
    }


async def compute_daily_rate(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    workflow: Workflow,
    days: int,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Per-day series for the dashboard sparklines. Returns a dense
    list — days with zero runs get explicit 0 rows so the frontend
    can render a continuous chart without gap-filling logic."""
    from datetime import UTC

    today = (now or datetime.now(UTC)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    since = today - timedelta(days=days - 1)
    until = today + timedelta(days=1)

    sparse = await _da.aggregate_daily_rate(
        session,
        org_id=org_id,
        workflow_id=workflow.id,
        since=since,
        until=until,
    )
    by_date = {row["date"]: row for row in sparse}
    dense: list[dict[str, Any]] = []
    for i in range(days):
        day = since + timedelta(days=i)
        key = day.date().isoformat()
        if key in by_date:
            dense.append(by_date[key])
        else:
            dense.append(
                {
                    "date": key,
                    "enrolled": 0,
                    "completed": 0,
                    "goal_reached": 0,
                }
            )
    return dense


__all__ = [
    "compute_daily_rate",
    "compute_workflow_metrics",
]
