"""Workflows — Module C of the three-track plan.

Multi-step branching flowcharts on top of the
``tasks/automation-engine`` event bus + the
``tasks/template-library`` central library. Where the automation
engine fires single-event triggers, workflows orchestrate a node
graph:

    [Trigger] → [Condition] → [Send action] → [Delay] →
    [Branch] → [Record update] → [Goal] / [End]

Step 1 lands the schema + ORM + Pydantic + the action-registry
stub. Subsequent steps fill in the service, router, engine, and
the React-flow-style canvas UI.

The runtime concept map:

  * ``Workflow``        — definition (name, status, ``graph`` JSONB).
  * ``WorkflowVersion`` — append-only history (operator publishes;
                          a new version row is written).
  * ``WorkflowRun``     — one enrolment (typically per contact) of a
                          workflow at a specific version. Carries
                          ``state`` JSONB so nodes can read variables
                          emitted earlier.
  * ``WorkflowStepRun`` — append-only per-node audit log. Step 19
                          drives the run-history UI from this.
  * ``WorkflowFolder``  — operator's organisational tree for the
                          list page (Step 13).

This module never imports from ``packs/`` (Rule 1). Every table
carries ``org_id`` + RLS from day one (Rule 2). Cross-module reads
go through the OWNING module's data_access (Rule from manager spec
2026-06-25).
"""

# tasks/workflows Step 5 — side-effect: register the universal
# event-bus subscriber against every catalog event the moment the
# workflows package is imported. The Step-4 engine then walks
# matching workflows on every published event. Idempotent — re-runs
# of the registration loop are no-ops via the bus's per-handler
# idempotency check.
from src.app.core.workflows.trigger_handlers import register_subscribers

register_subscribers()

# tasks/workflows Step 6 — side-effect: register the branch + switch
# action handlers so the engine resolves ``branch.if`` / ``branch.switch``
# nodes without a special case. Import-only — the module's top-level
# ``register()`` fires automatically.
# tasks/workflows Step 7 — side-effect: register the seven Send
# action handlers (email / WhatsApp / SMS / Facebook / Instagram /
# push / Slack). Same import-only pattern as flow_control.
# tasks/workflows Step 8 — side-effect: register the nine Record
# action handlers (update_contact_field / update_lead_field /
# update_lead_stage / create_task / create_note / create_appointment /
# create_quote / create_invoice / create_order). The quote + order
# handlers are placeholders that raise ActionNotImplemented until
# core/quotes + core/orders ship.
# tasks/workflows Step 9 — side-effect: register the five Routing
# action handlers (round_robin / least_loaded / territory / skill /
# specific_user). Round-robin pointer state lives on
# ``tbl_org_settings.routing_state`` (column added by migration
# 0138_org_settings_routing_state).
# tasks/workflows Step 10 — side-effect: register the five tagging
# handlers (add_tag / remove_tag / add_to_list / remove_from_list /
# set_lead_score) and the eight lifecycle handlers (mark_converted /
# mark_unsubscribed / block_contact / archive_contact /
# enroll_in_workflow / enroll_in_sequence / remove_from_workflow /
# remove_from_sequence). add_to_list / remove_from_list /
# block_contact / archive_contact are placeholders that raise
# ActionNotImplemented until the underlying CRM modules ship.
from src.app.core.workflows.actions import (
    flow_control,  # noqa: F401
    lifecycle,  # noqa: F401
    records,  # noqa: F401
    routing,  # noqa: F401
    send,  # noqa: F401
    tagging,  # noqa: F401
)
