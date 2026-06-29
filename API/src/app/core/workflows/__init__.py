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
from src.app.core.workflows.actions import flow_control  # noqa: F401
