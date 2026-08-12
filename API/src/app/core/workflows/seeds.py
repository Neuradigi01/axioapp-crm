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
from dataclasses import dataclass, field
from typing import Any

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
    initial_status = WorkflowStatus.active if entry.auto_activate else WorkflowStatus.draft
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
            workflow = _build_seed_workflow(org_id=org_id, user_id=user_id, entry=entry)
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
    result = await install_seeded_workflows(session, org_id=org_id, user_id=user_id)
    return result["installed"]


# ==========================================================================
# Preset workflows — single-step mirrors of the ex-automation seeds.
#
# workflows-absorb-automation Step 2: replaces the
# ``core.automation.seeds.install_default_org_seeds`` call that used to
# run inside ``core.tenants.service.create_organization``. Each spec
# below matches one of the ten preset automation triggers 1:1 — same
# event, same channel, same recipient resolver, same conditions, same
# template. Difference: seeds a single-step Workflow row instead of an
# AutomationTrigger row.
#
# Seeded as ``status='active'`` because the source automations were
# active-on-seed too — Welcome / Confirmation / Reminders / Invoice
# notifications / Birthday are transactional sends operators expect to
# "just work" the moment a new org boots. Multi-step nurture flows
# (Step 20's 15 gallery seeds) continue to seed as drafts.
#
# Each spec references a helper in :mod:`core.templates.seeds` (already
# in place from the automation-engine track) so template + workflow
# variables never drift out of sync — the workflow's send node carries
# the exact template_id the seed helper returned.
# ==========================================================================


@dataclass(frozen=True)
class _PresetSpec:
    """One preset workflow — everything needed to build + insert it."""

    name: str
    event_type: str
    # ConversationChannel string value. Must match a registered send
    # action node type — see ``core/workflows/actions/send.py``.
    channel: str
    node_type: str
    # ``config.recipient`` value the send node lands with. Either a
    # bare string (stock resolver by name — ``"contact.email"`` /
    # ``"contact.phone"``) or a dict for parameterised resolvers
    # (e.g. ``{"kind": "custom", "path": "user.email"}`` for
    # signup events where the recipient lives at the trigger
    # payload path rather than on a persisted user row).
    recipient: str | dict[str, Any]
    conditions: dict[str, Any] = field(default_factory=dict)
    delay_seconds: int = 0
    # Attribute name in ``core.templates.seeds`` — resolved at call time
    # via ``getattr`` so this module doesn't force-import every template
    # seeder at import.
    template_seeder: str = ""


_PRESET_SPECS: list[_PresetSpec] = [
    _PresetSpec(
        name="User Welcome",
        event_type="user.signed_up",
        channel="email",
        node_type="send.email",
        # Workflow's ``user.email`` resolver looks up a user by ID
        # (from ``node.config.recipient.user_id`` or falls back to
        # ``workflow.created_by_user_id``) — neither is populated for
        # a signup event, so the resolver would return None + skip.
        # Use ``custom`` with the payload path instead — mirrors what
        # the automation module's ``user.email`` resolver did (read
        # ``payload.user.email``).
        recipient={"kind": "custom", "path": "user.email"},
        template_seeder="seed_user_welcome_template",
    ),
    _PresetSpec(
        name="Lead Confirmation",
        event_type="lead.created",
        channel="email",
        node_type="send.email",
        recipient="contact.email",
        # workflow condition AST uses ``path`` (not ``field``) + ``neq``
        # (not ``ne``) — see ``core/events/conditions.py``. The old
        # automation seed shape is auto-translated by migration
        # ``0178_fix_wf_condition_shape`` for existing orgs; new
        # orgs get the correct shape here directly.
        conditions={"path": "source", "op": "neq", "value": "bulk_import"},
        template_seeder="seed_lead_confirmation_template",
    ),
    _PresetSpec(
        name="Appointment Booked",
        event_type="appointment.booked",
        channel="whatsapp",
        node_type="send.whatsapp",
        recipient="contact.phone",
        template_seeder="seed_appointment_booked_template",
    ),
    _PresetSpec(
        name="Appointment Reminder 24h",
        event_type="appointment.reminder_24h",
        channel="whatsapp",
        node_type="send.whatsapp",
        recipient="contact.phone",
        template_seeder="seed_appointment_reminder_24h_template",
    ),
    _PresetSpec(
        name="Appointment Reminder 1h",
        event_type="appointment.reminder_1h",
        channel="whatsapp",
        node_type="send.whatsapp",
        recipient="contact.phone",
        template_seeder="seed_appointment_reminder_1h_template",
    ),
    _PresetSpec(
        name="Invoice Sent",
        event_type="invoice.sent",
        channel="email",
        node_type="send.email",
        recipient="contact.email",
        template_seeder="seed_invoice_sent_template",
    ),
    _PresetSpec(
        name="Invoice Paid",
        event_type="invoice.paid",
        channel="email",
        node_type="send.email",
        recipient="contact.email",
        template_seeder="seed_invoice_paid_template",
    ),
    _PresetSpec(
        name="Invoice Overdue 7d",
        event_type="invoice.overdue_7d",
        channel="email",
        node_type="send.email",
        recipient="contact.email",
        template_seeder="seed_invoice_overdue_template",
    ),
    _PresetSpec(
        name="Contact Birthday",
        event_type="contact.birthday",
        channel="whatsapp",
        node_type="send.whatsapp",
        recipient="contact.phone",
        template_seeder="seed_contact_birthday_template",
    ),
    _PresetSpec(
        name="Lead Stale 30d",
        event_type="lead.stale_30d",
        channel="email",
        node_type="send.email",
        recipient="contact.email",
        template_seeder="seed_lead_stale_30d_template",
    ),
    _PresetSpec(
        name="Task Assigned",
        event_type="task.assigned",
        channel="email",
        node_type="send.email",
        # Recipient is the assignee, whose email is embedded in the
        # trigger payload at `assignee.email` by the tasks publisher.
        # `custom` walks the payload; no new resolver code needed.
        recipient={"kind": "custom", "path": "assignee.email"},
        template_seeder="seed_task_assigned_template",
    ),
    _PresetSpec(
        name="Task Completed",
        event_type="task.completed",
        channel="email",
        node_type="send.email",
        # Same recipient shape as Task Assigned — the task's assignee
        # is who should hear about the completion so they see the
        # confirmation in their inbox alongside the create email.
        recipient={"kind": "custom", "path": "assignee.email"},
        template_seeder="seed_task_completed_template",
    ),
]

# Sentinel category so the workflows page + backfill migration can
# identify preset rows without a schema change. Matches the Step-1
# migration's ``'Migrated Automation'`` marker semantically — both
# categories signal "this workflow replaces what used to be an
# automation".
_PRESET_CATEGORY = "Preset Workflow"


def _short(prefix: str) -> str:
    """Deterministic-ish short node id — matches the gallery seed
    convention (``t-<hex8>`` / ``s-<hex8>``)."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _build_preset_graph(spec: _PresetSpec, *, template_id: str) -> dict[str, Any]:
    """Compose ``{nodes, edges}`` for a single-step preset workflow.
    Layout: trigger → (optional flow.wait) → send. No goal node — the
    send is terminal + ``goal_node_id`` stays NULL on the row."""
    trigger_id = _short("t")
    send_id = _short("s")
    nodes: list[dict[str, Any]] = [
        {
            "id": trigger_id,
            "type": "trigger",
            "position": {"x": 240, "y": 80},
            "config": {
                "label": "Trigger",
                "event_type": spec.event_type,
                "re_enrollment_rule": "once",
                "conditions": spec.conditions or None,
            },
        },
    ]
    edges: list[dict[str, Any]] = []
    previous = trigger_id

    if spec.delay_seconds > 0:
        wait_id = _short("w")
        nodes.append(
            {
                "id": wait_id,
                "type": "flow.wait",
                "position": {"x": 240, "y": 220},
                "config": {
                    "label": "Wait",
                    "delay_seconds": spec.delay_seconds,
                    "max_wait_seconds": spec.delay_seconds,
                },
            }
        )
        edges.append({"id": _short("e"), "source": previous, "target": wait_id, "label": None})
        previous = wait_id

    nodes.append(
        {
            "id": send_id,
            "type": spec.node_type,
            "position": {
                "x": 240,
                "y": 220 + (140 if spec.delay_seconds > 0 else 0),
            },
            "config": {
                "label": "Send",
                "template_id": template_id,
                # Workflow send actions read ``config.recipient`` (not
                # ``config.recipient_resolver`` — that was the automation
                # module's key). Migration ``0179_fix_wf_send_recipient``
                # translates the shape on existing rows; this seed writes
                # the right key from the start for new orgs.
                "recipient": spec.recipient,
            },
        }
    )
    edges.append({"id": _short("e"), "source": previous, "target": send_id, "label": None})

    return {"nodes": nodes, "edges": edges}


async def install_preset_workflows(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Install the ten single-step preset workflows into ``org_id``.

    Called from ``core.tenants.service.create_organization`` — replaces
    the ``core.automation.seeds.install_default_org_seeds`` call the
    previous org-creation path used. Each preset seeds a template first
    (via ``core.templates.seeds``) so the workflow's send node carries a
    real ``template_id``.

    Idempotent on ``(org_id, lower(name))`` via
    ``data_access.get_workflow_by_name`` — safe to re-run from the
    Step-2 backfill migration + the org-creation hook without producing
    duplicates. Returns ``{"installed": N, "skipped": M}`` so the
    caller (org-create hook / backfill) can log outcomes.

    Seeds land as ``status='active'`` — matches the transactional
    behaviour of the ex-automation seeds, so new orgs' Welcome / Lead
    Confirmation / Reminder / Birthday flows fire immediately without
    operator activation. Multi-step marketing workflows continue to
    seed as drafts via :func:`install_seeded_workflows`.

    Caller owns the transaction — no ``commit`` inside this function.
    """
    from src.app.core.templates import seeds as _tmpl_seeds
    from src.app.core.workflows import data_access as _wf_da

    installed = 0
    skipped = 0

    for spec in _PRESET_SPECS:
        existing = await _wf_da.get_workflow_by_name(session, org_id=org_id, name=spec.name)
        if existing is not None:
            skipped += 1
            continue

        template_fn = getattr(_tmpl_seeds, spec.template_seeder)
        template = await template_fn(session, org_id=org_id)

        graph_dict = _build_preset_graph(spec, template_id=str(template.id))
        workflow = Workflow(
            id=uuid.uuid4(),
            org_id=org_id,
            name=spec.name,
            description=(
                f"Preset workflow — fires on {spec.event_type}. Sends via {spec.channel}."
            ),
            category=_PRESET_CATEGORY,
            status=WorkflowStatus.active,
            current_version=1,
            re_enrollment_rule=WorkflowReEnrollmentRule.once,
            is_marketing=False,
            is_system_default=False,
            graph=graph_dict,
            goal_node_id=None,
            cost_per_run_cents=0,
            enabled_event_types=[spec.event_type],
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
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
                change_note="Initial preset seed (ex-automation)",
                created_by_user_id=user_id,
            )
        )
        await session.flush()
        installed += 1
        logger.info(
            "workflows.preset_seed installed org=%s name=%s workflow=%s template=%s",
            org_id,
            spec.name,
            workflow.id,
            template.id,
        )

    return {"installed": installed, "skipped": skipped}


# Public preset name list — the backfill migration reads this to
# know which names to check for missing rows without duplicating the
# spec table.
PRESET_WORKFLOW_NAMES: list[str] = [spec.name for spec in _PRESET_SPECS]


__all__ = [
    "PRESET_WORKFLOW_NAMES",
    "install_preset_workflows",
    "install_seeded_workflows",
    "seed_default_workflows",
]
