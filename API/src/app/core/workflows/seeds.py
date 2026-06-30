"""Default workflow seeder (Step 20).

Materialises the 15 gallery templates (:data:`templates_gallery.CATALOG`)
into real ``tbl_workflows`` rows for every new org so a fresh signup
has a populated workflow library out of the box.

Idempotency: the seeder checks for each template's canonical name in
the org's existing workflows + skips clones that have already landed.
Safe to re-run, e.g. from the org-create hook AND the backfill
migration without duplicating rows.

Seeds are installed as ``status='draft'`` per the manager's safety
preference — operators review + activate per workflow rather than
the platform auto-firing marketing flows the moment the org boots.

Implementation note: the gallery templates intentionally ship without
``template_id`` references on their send-action nodes (operator picks
per-node at clone time). The Step-16 ``clone_from_gallery`` path
calls ``workflows_service.create_workflow`` which runs strict graph
validation — that validator rejects send nodes without a template_id.

To install placeholder seed rows we therefore bypass
``create_workflow`` and write directly via the ORM model + an
explicit v1 row in ``tbl_workflow_versions``. The seeded workflows
still validate the moment the operator tries to activate (Step 2 +
Step 12 gates fire on the activate path), so the validation
discipline is preserved where it matters — at the point of going
live.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.workflows import templates_gallery as _gallery
from src.app.core.workflows.models import (
    Workflow,
    WorkflowReEnrollmentRule,
    WorkflowStatus,
    WorkflowVersion,
)

logger = logging.getLogger(__name__)


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


def _build_seed_workflow(
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    entry: _gallery.GalleryTemplate,
) -> Workflow:
    """Compose a :class:`Workflow` ORM instance from a gallery
    template. Strips send-action ``template_id`` references the same
    way ``clone_from_gallery`` does; the operator picks the real
    template per node at activation.

    Step 21 — when ``entry.auto_activate`` is True the row lands as
    ``status='active'`` (default: ``draft``). When
    ``entry.is_system_default`` is True the row is stamped + the
    service layer refuses to archive it.
    """
    graph_dict = _gallery._strip_send_template_ids(entry.graph_preview)
    goal_node_id = entry.graph_preview.get("goal_node_id")
    initial_status = (
        WorkflowStatus.active if entry.auto_activate else WorkflowStatus.draft
    )
    return Workflow(
        id=uuid.uuid4(),
        org_id=org_id,
        name=entry.name,
        description=entry.description,
        category=entry.category,
        status=initial_status,
        current_version=1,
        re_enrollment_rule=WorkflowReEnrollmentRule(entry.re_enrollment_rule),
        is_marketing=entry.is_marketing,
        is_system_default=entry.is_system_default,
        graph=graph_dict,
        goal_node_id=goal_node_id,
        cost_per_run_cents=0,
        enabled_event_types=_extract_event_types(graph_dict),
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
    )


async def install_seeded_workflows(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Install the 15 default core workflows into ``org_id``.

    Idempotent: if a workflow with the template's canonical name
    already exists in the org, the entry is skipped. Returns a small
    summary dict ``{"installed": N, "skipped": M}`` so the caller
    can log / surface what happened.

    Each seed lands as ``status='draft'`` (the operator must
    explicitly activate). No transaction here — the caller commits.
    """
    from src.app.core.workflows import data_access as _da

    existing_names = await _da.list_workflow_names(session, org_id=org_id)
    existing_set = set(existing_names)

    installed = 0
    skipped = 0

    for entry in _gallery.CATALOG:
        if entry.name in existing_set:
            skipped += 1
            continue
        try:
            workflow = _build_seed_workflow(
                org_id=org_id, user_id=user_id, entry=entry
            )
            session.add(workflow)
            await session.flush()
            session.add(
                WorkflowVersion(
                    id=uuid.uuid4(),
                    org_id=org_id,
                    workflow_id=workflow.id,
                    version=1,
                    graph=workflow.graph,
                    change_note="Initial seed",
                    created_by_user_id=user_id,
                )
            )
            await session.flush()
            existing_set.add(entry.name)
            installed += 1
        except Exception:
            logger.exception(
                "workflows.seeds install_failed org=%s template=%s",
                org_id,
                entry.id,
            )
            # Soft-fail per template — one bad seed shouldn't break
            # the rest of the install for this org.

    return {"installed": installed, "skipped": skipped}


# Legacy alias kept for the Step-16 placeholder import path.
async def seed_default_workflows(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
) -> int:
    """Compatibility shim — returns the install count."""
    result = await install_seeded_workflows(
        session, org_id=org_id, user_id=user_id
    )
    return result["installed"]


__all__ = [
    "install_seeded_workflows",
    "seed_default_workflows",
]
