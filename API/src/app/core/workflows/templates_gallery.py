"""Gallery of default workflow templates the operator can clone from.

Hard-coded list of 15 entries — same 15 Step 20 will seed into every
new org. This module exposes them through `list_gallery()` for the
``GET /workflows/gallery`` endpoint and through
:func:`clone_from_gallery` for the ``POST .../clone`` endpoint.

The catalog entries store a `graph_preview` that mirrors the
``tbl_workflows.graph`` shape so the frontend preview modal can
re-use the Step-14 canvas in read-only mode. When the operator clones
a template, :func:`clone_from_gallery` calls into
``workflows.service.create_workflow`` after stripping every
`template_id` reference on send-action nodes — the operator's org
hasn't created those templates yet, so the cloned workflow lands as a
draft with validation markers on the send nodes (Step-15 editor
prompts the operator to pick a template per node before activation).

Step 20 will later add real graphs to this module so the preview
matches the seeded workflow. For Step 16, each entry ships a tiny
placeholder graph (trigger → 1-2 actions → goal) so the gallery is
inspectable from day one.

Furniture / pack-shipped workflows (Layer 2) will register additional
gallery entries via ``pack.yaml`` — :func:`list_gallery` returns the
merged list. For Step 16 only the core 15 are present.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.workflows import service as workflows_service
from src.app.core.workflows.exceptions import DuplicateWorkflowName
from src.app.core.workflows.models import Workflow
from src.app.core.workflows.schemas import (
    WorkflowCreate,
    WorkflowGraph,
)

# Categories the frontend tabs render. Keep stable string keys; the
# UI maps them to display labels + Lucide icons.
CATEGORY_SALES = "Sales"
CATEGORY_QUOTES = "Quotes & invoices"
CATEGORY_ONBOARDING = "Customer onboarding"
CATEGORY_ENGAGEMENT = "Engagement"
CATEGORY_WALK_IN = "Walk-in"
CATEGORY_INTERNAL = "Internal"


@dataclass(frozen=True, slots=True)
class GalleryTemplate:
    """One gallery entry.

    ``id`` is a stable string identifier (used in the URL of the
    clone endpoint). ``graph_preview`` is the same dict shape as
    ``tbl_workflows.graph`` so the canvas can render it directly. The
    clone path strips template_id references before persisting.

    Step 21 adds two flags:

      * ``auto_activate`` — seeder installs ``status='active'`` (vs
        the default ``draft``). Use ONLY for internal-only workflows
        with no contact-facing sends so a freshly-provisioned org
        doesn't blast marketing emails before the operator reviews.
      * ``is_system_default`` — seeder stamps the column +
        ``service.archive_workflow`` refuses to archive the row.
        Operator can still pause + edit, so they can tune cadence
        without dropping the day-one safety net.
    """

    id: str
    name: str
    description: str
    category: str
    channels: list[str]
    goal_node_label: str
    est_setup_time_minutes: int
    est_completion_rate_pct: int
    screenshot_url: str | None
    graph_preview: dict[str, Any] = field(default_factory=dict)
    is_marketing: bool = True
    re_enrollment_rule: str = "once"
    auto_activate: bool = False
    is_system_default: bool = False


# --- Placeholder graph factory ------------------------------------------


def _placeholder_graph(
    *,
    trigger_event_type: str,
    send_actions: list[tuple[str, str]],
    goal_label: str,
) -> dict[str, Any]:
    """Build a minimal trigger → send-action(s) → goal graph.

    ``send_actions`` is a list of ``(node_type, label)`` pairs — each
    becomes a send node. Step 20 will replace this with real graphs;
    for Step 16 the placeholder is enough for the preview canvas.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    trigger_id = f"t-{uuid.uuid4().hex[:8]}"
    nodes.append(
        {
            "id": trigger_id,
            "type": "trigger",
            "position": {"x": 240, "y": 80},
            "config": {
                "label": "Trigger",
                "event_type": trigger_event_type,
                "re_enrollment_rule": "once",
                "conditions": None,
            },
        }
    )

    previous = trigger_id
    for idx, (node_type, label) in enumerate(send_actions):
        node_id = f"a-{uuid.uuid4().hex[:8]}"
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "position": {"x": 240, "y": 200 + idx * 140},
                "config": {
                    "label": label,
                    # template_id intentionally absent — clone path
                    # leaves it null so the operator picks per node.
                },
            }
        )
        edges.append(
            {
                "id": f"e-{uuid.uuid4().hex[:8]}",
                "source": previous,
                "target": node_id,
                "label": None,
            }
        )
        previous = node_id

    goal_id = f"g-{uuid.uuid4().hex[:8]}"
    nodes.append(
        {
            "id": goal_id,
            "type": "flow_control.goal",
            "position": {"x": 240, "y": 200 + len(send_actions) * 140},
            "config": {"label": goal_label, "name": goal_label},
        }
    )
    edges.append(
        {
            "id": f"e-{uuid.uuid4().hex[:8]}",
            "source": previous,
            "target": goal_id,
            "label": None,
        }
    )
    return {"nodes": nodes, "edges": edges, "goal_node_id": goal_id}


# --- Step 21: Lead Auto-Triage graph (the system-default day-one
# safety net). Matches the Salesforce / HubSpot / Zoho default-
# assignment pattern: every new lead gets a route + stamp + notify +
# follow-up task, with a Slack alert on the hot path. Internal-only —
# no contact-facing sends. -------------------------------------------


def _lead_auto_triage_graph() -> dict[str, Any]:
    """Build the 10-node Lead Auto-Triage graph.

    Layout (top-to-bottom, two branch.switch nodes drive the source +
    score paths, all paths converge on the routing node):

        trigger(lead.created)
          → branch.switch by lead.source     # tag with priority + source
              ↓ (default arm)
          → branch.switch by score band      # senior pool vs sales pool
              ↓ (chosen arm sets pool var, default = "sales")
          → routing.round_robin
          → record.update_lead_field
          → record.update_contact_field
          → tagging.add_tag
          → flow_control.notify_user
          → record.create_task
          → flow_control.goal "Lead triaged"

    Slack alert for hot leads is wired off the score-branch's "hot"
    arm with its own goal.
    """
    trigger_id = "lead-triage-trigger"
    source_branch_id = "lead-triage-source-branch"
    score_branch_id = "lead-triage-score-branch"
    route_id = "lead-triage-route"
    stamp_lead_id = "lead-triage-stamp-lead"
    stamp_contact_id = "lead-triage-stamp-contact"
    tag_id = "lead-triage-tag"
    notify_id = "lead-triage-notify"
    task_id = "lead-triage-task"
    goal_id = "lead-triage-goal"
    slack_id = "lead-triage-slack-hot"
    slack_goal_id = "lead-triage-slack-goal"

    nodes: list[dict[str, Any]] = [
        {
            "id": trigger_id,
            "type": "trigger",
            "position": {"x": 360, "y": 40},
            "config": {
                "label": "New lead created",
                "event_type": "lead.created",
                "re_enrollment_rule": "once",
                "conditions": None,
            },
        },
        {
            "id": source_branch_id,
            "type": "branch.switch",
            "position": {"x": 360, "y": 180},
            "config": {
                "label": "By source",
                "path": "lead.source",
                "branches": [
                    {"label": "paid_ad", "value": "paid_ad"},
                    {"label": "web_form", "value": "web_form"},
                    {"label": "import", "value": "import"},
                    {"label": "manual", "value": "manual"},
                ],
            },
        },
        {
            "id": score_branch_id,
            "type": "branch.switch",
            "position": {"x": 360, "y": 340},
            "config": {
                "label": "By score band",
                "path": "lead.score_band",
                "branches": [
                    {"label": "hot", "value": "hot"},
                    {"label": "warm", "value": "warm"},
                ],
            },
        },
        {
            "id": route_id,
            "type": "routing.round_robin",
            "position": {"x": 360, "y": 500},
            "config": {
                "label": "Round-robin assign",
                "role": "Sales",
                "fallback_role": "Owner",
            },
        },
        {
            "id": stamp_lead_id,
            "type": "record.update_lead_field",
            "position": {"x": 360, "y": 640},
            "config": {
                "label": "Stamp lead",
                "fields": {
                    "status": "new",
                    "assigned_to_id": "{{routing.assignee_id}}",
                    "first_touch_at": "{{now}}",
                },
            },
        },
        {
            "id": stamp_contact_id,
            "type": "record.update_contact_field",
            "position": {"x": 360, "y": 780},
            "config": {
                "label": "Sync contact owner",
                "fields": {
                    "assigned_to_id": "{{routing.assignee_id}}",
                },
            },
        },
        {
            "id": tag_id,
            "type": "tagging.add_tag",
            "position": {"x": 360, "y": 920},
            "config": {
                "label": "Tag priority + source",
                "tags": ["{{lead.source}}", "auto-triaged"],
            },
        },
        {
            "id": notify_id,
            "type": "flow_control.notify_user",
            "position": {"x": 360, "y": 1060},
            "config": {
                "label": "Notify assignee",
                "user_id": "{{routing.assignee_id}}",
                "title": "New lead assigned to you",
                "body": (
                    "{{lead.full_name}} from {{lead.source}} "
                    "(score {{lead.score}})"
                ),
                "channels": ["in_app", "email", "push"],
            },
        },
        {
            "id": task_id,
            "type": "record.create_task",
            "position": {"x": 360, "y": 1200},
            "config": {
                "label": "Follow-up task",
                "title": "Follow up with {{lead.full_name}}",
                "description": (
                    "Lead from {{lead.source}}, score {{lead.score}}. "
                    "Contact: {{contact.email}} / {{contact.phone}}"
                ),
                "assigned_to_id": "{{routing.assignee_id}}",
                "due_in_hours": 24,
                "priority": "normal",
            },
        },
        {
            "id": goal_id,
            "type": "flow_control.goal",
            "position": {"x": 360, "y": 1340},
            "config": {
                "label": "Lead triaged",
                "name": "Lead triaged + assigned",
            },
        },
        {
            "id": slack_id,
            "type": "send.slack",
            "position": {"x": 640, "y": 500},
            "config": {
                "label": "Slack #sales-hot-leads",
                "channel": "#sales-hot-leads",
                "message": (
                    ":fire: Hot lead {{lead.full_name}} "
                    "(score {{lead.score}}) — assigned to "
                    "{{routing.assignee_name}}"
                ),
            },
        },
        {
            "id": slack_goal_id,
            "type": "flow_control.goal",
            "position": {"x": 640, "y": 640},
            "config": {
                "label": "Hot lead alert sent",
                "name": "Hot lead Slack alert",
            },
        },
    ]

    edges: list[dict[str, Any]] = [
        # Trigger → source branch
        {"id": "e-1", "source": trigger_id, "target": source_branch_id, "label": None},
        # Source branch (every arm) → score branch
        {"id": "e-2a", "source": source_branch_id, "target": score_branch_id, "label": "paid_ad"},
        {"id": "e-2b", "source": source_branch_id, "target": score_branch_id, "label": "web_form"},
        {"id": "e-2c", "source": source_branch_id, "target": score_branch_id, "label": "import"},
        {"id": "e-2d", "source": source_branch_id, "target": score_branch_id, "label": "manual"},
        {"id": "e-2e", "source": source_branch_id, "target": score_branch_id, "label": "default"},
        # Score branch → main path (warm / default) + Slack on hot
        {"id": "e-3a", "source": score_branch_id, "target": route_id, "label": "warm"},
        {"id": "e-3b", "source": score_branch_id, "target": route_id, "label": "default"},
        {"id": "e-3c", "source": score_branch_id, "target": slack_id, "label": "hot"},
        # Slack → its own goal (hot path still falls through to main
        # via a second edge so the lead also gets the standard assign)
        {"id": "e-4", "source": slack_id, "target": route_id, "label": None},
        {"id": "e-4b", "source": slack_id, "target": slack_goal_id, "label": None},
        # Main flow
        {"id": "e-5", "source": route_id, "target": stamp_lead_id, "label": None},
        {"id": "e-6", "source": stamp_lead_id, "target": stamp_contact_id, "label": None},
        {"id": "e-7", "source": stamp_contact_id, "target": tag_id, "label": None},
        {"id": "e-8", "source": tag_id, "target": notify_id, "label": None},
        {"id": "e-9", "source": notify_id, "target": task_id, "label": None},
        {"id": "e-10", "source": task_id, "target": goal_id, "label": None},
    ]

    return {"nodes": nodes, "edges": edges, "goal_node_id": goal_id}


# --- The 15 catalogue entries -------------------------------------------


CATALOG: tuple[GalleryTemplate, ...] = (
    # Sales lifecycle (3)
    GalleryTemplate(
        # Step 21 — renamed from "New Lead Welcome + Auto-Assign" +
        # rebuilt as the full 10-node intake graph. Internal-only
        # (round-robin assign + stamp + notify + follow-up task +
        # Slack on hot path) — no contact-facing email send. Installs
        # active + is_system_default per the day-one safety net plan.
        id="lead.auto_triage",
        name="New Lead Auto-Triage",
        description=(
            "Round-robin assign every new lead to a sales rep, stamp "
            "the status, notify the assignee, create a follow-up task, "
            "and ping #sales-hot-leads on high-score arrivals. "
            "Day-one system default — install active."
        ),
        category=CATEGORY_SALES,
        channels=["internal", "slack"],
        goal_node_label="Lead triaged",
        est_setup_time_minutes=0,
        est_completion_rate_pct=98,
        screenshot_url=None,
        graph_preview=_lead_auto_triage_graph(),
        is_marketing=False,
        auto_activate=True,
        is_system_default=True,
    ),
    GalleryTemplate(
        id="lead.hot_nurture",
        name="Hot Lead Nurture (score ≥75)",
        description="3-touch email + WhatsApp sequence for leads with score ≥ 75.",
        category=CATEGORY_SALES,
        channels=["email", "whatsapp"],
        goal_node_label="Lead converted",
        est_setup_time_minutes=10,
        est_completion_rate_pct=68,
        screenshot_url=None,
        graph_preview=_placeholder_graph(
            trigger_event_type="lead.stage_changed",
            send_actions=[
                ("send.email", "Touch 1 — Welcome"),
                ("send.whatsapp", "Touch 2 — Case study"),
                ("send.email", "Touch 3 — Offer"),
            ],
            goal_label="Lead converted",
        ),
    ),
    GalleryTemplate(
        id="lead.stale_recovery",
        name="Stale Lead Recovery (30 / 60 / 90 days)",
        description="Re-engage leads with no activity in 30 / 60 / 90 days.",
        category=CATEGORY_SALES,
        channels=["email", "whatsapp"],
        goal_node_label="Lead re-engaged",
        est_setup_time_minutes=15,
        est_completion_rate_pct=42,
        screenshot_url=None,
        graph_preview=_placeholder_graph(
            trigger_event_type="lead.updated",
            send_actions=[
                ("send.email", "30-day check-in"),
                ("send.whatsapp", "60-day reminder"),
                ("send.email", "90-day final touch"),
            ],
            goal_label="Lead re-engaged",
        ),
    ),
    # Quotes & invoices (3)
    GalleryTemplate(
        id="quote.follow_up",
        name="Quote Follow-Up (3-touch)",
        description="3-touch follow-up after a quote is sent and not viewed.",
        category=CATEGORY_QUOTES,
        channels=["email", "whatsapp"],
        goal_node_label="Quote viewed",
        est_setup_time_minutes=8,
        est_completion_rate_pct=58,
        screenshot_url=None,
        graph_preview=_placeholder_graph(
            trigger_event_type="quote.sent",
            send_actions=[
                ("send.email", "Day 1 check-in"),
                ("send.whatsapp", "Day 3 reminder"),
                ("send.email", "Day 7 final touch"),
            ],
            goal_label="Quote viewed",
        ),
    ),
    GalleryTemplate(
        id="quote.accepted_thanks",
        name="Quote Accepted Thank-You",
        description="Send a thank-you email when a quote is accepted.",
        category=CATEGORY_QUOTES,
        channels=["email"],
        goal_node_label="Onboarding kickoff",
        est_setup_time_minutes=3,
        est_completion_rate_pct=95,
        screenshot_url=None,
        graph_preview=_placeholder_graph(
            trigger_event_type="quote.accepted",
            send_actions=[("send.email", "Thank-you email")],
            goal_label="Onboarding kickoff",
        ),
    ),
    GalleryTemplate(
        id="invoice.overdue_escalation",
        name="Invoice Overdue Escalation (7 / 14 / 30 days)",
        description="Escalating reminders for overdue invoices.",
        category=CATEGORY_QUOTES,
        channels=["email", "whatsapp", "sms"],
        goal_node_label="Invoice paid",
        est_setup_time_minutes=12,
        est_completion_rate_pct=71,
        screenshot_url=None,
        graph_preview=_placeholder_graph(
            trigger_event_type="invoice.sent",
            send_actions=[
                ("send.email", "Day 7 reminder"),
                ("send.whatsapp", "Day 14 reminder"),
                ("send.sms", "Day 30 final notice"),
            ],
            goal_label="Invoice paid",
        ),
    ),
    # Customer onboarding (2)
    GalleryTemplate(
        id="customer.welcome_30d",
        name="New Customer Welcome (5-touch over 30 days)",
        description="5-touch onboarding sequence for new customers.",
        category=CATEGORY_ONBOARDING,
        channels=["email"],
        goal_node_label="Customer onboarded",
        est_setup_time_minutes=15,
        est_completion_rate_pct=80,
        screenshot_url=None,
        graph_preview=_placeholder_graph(
            trigger_event_type="invoice.paid",
            send_actions=[
                ("send.email", "Day 0 welcome"),
                ("send.email", "Day 3 getting started"),
                ("send.email", "Day 10 tips"),
                ("send.email", "Day 20 community"),
                ("send.email", "Day 30 review request"),
            ],
            goal_label="Customer onboarded",
        ),
    ),
    GalleryTemplate(
        id="customer.feedback_review",
        name="Post-Purchase Feedback + Review Request",
        description="Ask for feedback + Google review after first purchase.",
        category=CATEGORY_ONBOARDING,
        channels=["email", "whatsapp"],
        goal_node_label="Review submitted",
        est_setup_time_minutes=5,
        est_completion_rate_pct=37,
        screenshot_url=None,
        graph_preview=_placeholder_graph(
            trigger_event_type="invoice.paid",
            send_actions=[
                ("send.email", "Feedback survey"),
                ("send.whatsapp", "Review request"),
            ],
            goal_label="Review submitted",
        ),
    ),
    # Engagement (3)
    GalleryTemplate(
        id="engagement.birthday_anniversary",
        name="Birthday + Anniversary Greetings",
        description="Send greetings on the contact's birthday and customer anniversary.",
        category=CATEGORY_ENGAGEMENT,
        channels=["email", "whatsapp"],
        goal_node_label="Greeting sent",
        est_setup_time_minutes=4,
        est_completion_rate_pct=99,
        screenshot_url=None,
        graph_preview=_placeholder_graph(
            trigger_event_type="contact.updated",
            send_actions=[("send.whatsapp", "Birthday wish")],
            goal_label="Greeting sent",
        ),
    ),
    GalleryTemplate(
        id="engagement.reengagement_90d",
        name="Re-engagement (inactive 90+ days)",
        description="Win-back sequence for contacts inactive for 90+ days.",
        category=CATEGORY_ENGAGEMENT,
        channels=["email", "whatsapp"],
        goal_node_label="Contact re-engaged",
        est_setup_time_minutes=8,
        est_completion_rate_pct=23,
        screenshot_url=None,
        graph_preview=_placeholder_graph(
            trigger_event_type="contact.updated",
            send_actions=[
                ("send.email", "We miss you"),
                ("send.whatsapp", "Special offer"),
            ],
            goal_label="Contact re-engaged",
        ),
    ),
    GalleryTemplate(
        id="engagement.repeat_purchase",
        name="Repeat-Purchase Nurture",
        description="Nurture customers toward their second + third purchase.",
        category=CATEGORY_ENGAGEMENT,
        channels=["email"],
        goal_node_label="Repeat purchase",
        est_setup_time_minutes=10,
        est_completion_rate_pct=48,
        screenshot_url=None,
        graph_preview=_placeholder_graph(
            trigger_event_type="invoice.paid",
            send_actions=[
                ("send.email", "Cross-sell suggestion"),
                ("send.email", "Loyalty discount"),
            ],
            goal_label="Repeat purchase",
        ),
    ),
    # Walk-in (1)
    GalleryTemplate(
        id="walk_in.follow_up",
        name="Walk-In Follow-Up",
        description="WhatsApp follow-up the day after a walk-in left.",
        category=CATEGORY_WALK_IN,
        channels=["whatsapp"],
        goal_node_label="Walk-in converted",
        est_setup_time_minutes=4,
        est_completion_rate_pct=64,
        screenshot_url=None,
        graph_preview=_placeholder_graph(
            trigger_event_type="contact.created",
            send_actions=[("send.whatsapp", "Day 1 follow-up")],
            goal_label="Walk-in converted",
        ),
        is_marketing=False,
    ),
    # Internal / team (3)
    GalleryTemplate(
        id="internal.team_onboarding",
        name="New Team Member Onboarding",
        description="Internal onboarding tasks + Slack intro for a new rep.",
        category=CATEGORY_INTERNAL,
        channels=["slack"],
        goal_node_label="Onboarding complete",
        est_setup_time_minutes=12,
        est_completion_rate_pct=100,
        screenshot_url=None,
        graph_preview=_placeholder_graph(
            trigger_event_type="contact.created",
            send_actions=[("send.slack", "Welcome to the team")],
            goal_label="Onboarding complete",
        ),
        is_marketing=False,
    ),
    GalleryTemplate(
        # Step 21 — flagged as auto-active system default. Internal-
        # only (Slack send to a channel — no contact-facing message).
        id="internal.deal_won_alert",
        name="Deal Won Alert (Slack)",
        description=(
            "Internal Slack ping to #sales-wins when a lead converts. "
            "Day-one system default — install active."
        ),
        category=CATEGORY_INTERNAL,
        channels=["slack"],
        goal_node_label="Alert sent",
        est_setup_time_minutes=0,
        est_completion_rate_pct=100,
        screenshot_url=None,
        graph_preview=_placeholder_graph(
            trigger_event_type="lead.converted",
            send_actions=[("send.slack", "Deal won 🎉")],
            goal_label="Alert sent",
        ),
        is_marketing=False,
        auto_activate=True,
        is_system_default=True,
    ),
    GalleryTemplate(
        # Step 21 — flagged as auto-active system default. Internal
        # email to managers, no outbound to contacts.
        id="internal.daily_digest",
        name="Daily Digest to Sales Manager",
        description=(
            "Daily 9am IST internal digest of pipeline movement to "
            "the sales manager. Day-one system default — install active."
        ),
        category=CATEGORY_INTERNAL,
        channels=["email"],
        goal_node_label="Digest sent",
        est_setup_time_minutes=0,
        est_completion_rate_pct=100,
        screenshot_url=None,
        graph_preview=_placeholder_graph(
            trigger_event_type="lead.updated",
            send_actions=[("send.email", "Daily digest")],
            goal_label="Digest sent",
        ),
        is_marketing=False,
        auto_activate=True,
        is_system_default=True,
    ),
)


# --- Public API ---------------------------------------------------------


def list_gallery() -> list[dict[str, Any]]:
    """Catalog dump for ``GET /workflows/gallery``. Org-agnostic — every
    org sees the same list. Returns plain dicts so the router can
    project directly into the response model.
    """
    return [asdict(entry) for entry in CATALOG]


def get_template(template_id: str) -> GalleryTemplate | None:
    """Resolve a template by id. ``None`` when the id is unknown."""
    for entry in CATALOG:
        if entry.id == template_id:
            return entry
    return None


def _strip_send_template_ids(graph: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``graph`` with every send-action node's
    ``template_id`` removed (so the cloned workflow lands invalid
    until the operator picks a real template per the Step-15 editor's
    validation markers).
    """
    nodes = list(graph.get("nodes") or [])
    new_nodes: list[dict[str, Any]] = []
    for node in nodes:
        node_type = str(node.get("type") or "")
        if node_type.startswith("send.") or node_type.startswith("record.create_"):
            new_config = dict(node.get("config") or {})
            new_config.pop("template_id", None)
            new_config["__valid"] = False
            new_nodes.append({**node, "config": new_config})
        else:
            new_nodes.append(node)
    return {
        "nodes": new_nodes,
        "edges": list(graph.get("edges") or []),
    }


def _next_unique_name(base: str, existing_names: set[str]) -> str:
    """Append `(2)`, `(3)`, ... until the name isn't taken. Mirrors
    the templates-library clone naming convention from
    ``tasks/template-library/step-5-clone-from-default.md``.
    """
    if base not in existing_names:
        return base
    n = 2
    while True:
        candidate = f"{base} ({n})"
        if candidate not in existing_names:
            return candidate
        n += 1


async def clone_from_gallery(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    template_id: str,
    name: str | None = None,
    folder_id: uuid.UUID | None = None,
) -> Workflow:
    """Clone a gallery template into the org's library.

    Strips ``template_id`` from every send-action node (operator picks
    at clone time per the spec). Falls back to ``"Copy of <name>"``
    when no name is supplied. Auto-uniqifies the name with ``(2)``,
    ``(3)``, ... suffixes if the chosen name clashes — surfaces a
    409 only when the operator explicitly supplied a duplicate name.

    Raises :class:`KeyError` (caller maps to 404) when ``template_id``
    is unknown.
    """
    entry = get_template(template_id)
    if entry is None:
        raise KeyError(template_id)

    base_name = (name or f"Copy of {entry.name}").strip()

    # Auto-uniqify only when the operator didn't pick the name
    # themselves. When they did, a duplicate is a real 409.
    if name is None or name.strip() == "":
        existing = await _existing_names_in_org(session, org_id=org_id)
        base_name = _next_unique_name(base_name, existing)

    graph_dict = _strip_send_template_ids(entry.graph_preview)
    # Drop goal_node_id from graph_dict before re-validation — workflow
    # service's WorkflowCreate carries it as a separate field.
    goal_node_id = entry.graph_preview.get("goal_node_id")

    payload = WorkflowCreate(
        name=base_name,
        description=entry.description,
        category=entry.category,
        folder_id=folder_id,
        is_marketing=entry.is_marketing,
        re_enrollment_rule=entry.re_enrollment_rule,
        graph=WorkflowGraph.model_validate(graph_dict),
        goal_node_id=goal_node_id,
    )

    try:
        return await workflows_service.create_workflow(
            session, org_id=org_id, user_id=user_id, payload=payload
        )
    except DuplicateWorkflowName:
        # Auto-suffix on collision — even when an operator-supplied
        # name happens to clash, the gallery clone path is forgiving
        # (matches the spec's "idempotent on duplicate name → appends
        # `(2)` suffix" requirement).
        existing = await _existing_names_in_org(session, org_id=org_id)
        bumped = _next_unique_name(base_name, existing)
        payload = WorkflowCreate(
            name=bumped,
            description=entry.description,
            category=entry.category,
            folder_id=folder_id,
            is_marketing=entry.is_marketing,
            re_enrollment_rule=entry.re_enrollment_rule,
            graph=WorkflowGraph.model_validate(graph_dict),
            goal_node_id=goal_node_id,
        )
        return await workflows_service.create_workflow(
            session, org_id=org_id, user_id=user_id, payload=payload
        )


async def _existing_names_in_org(session: AsyncSession, *, org_id: uuid.UUID) -> set[str]:
    """Cached single-shot lookup of every workflow name in the org —
    avoids N+1 retries when auto-uniqifying."""
    from src.app.core.workflows import data_access as _da

    rows = await _da.list_workflow_names(session, org_id=org_id)
    return set(rows)


__all__ = [
    "CATALOG",
    "GalleryTemplate",
    "clone_from_gallery",
    "get_template",
    "list_gallery",
]
