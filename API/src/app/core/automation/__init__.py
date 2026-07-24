"""Automation engine — single-event trigger module.

Module B of the three-track plan (templates → automation → workflows).
Watches CRM domain events flowing through :mod:`core.events.bus`,
matches them against operator-configured ``tbl_automation_triggers``
rows, evaluates conditions, resolves the recipient, and queues a
Celery dispatch that renders the linked ``tbl_message_templates``
row and ships it via the channel adapter.

Step 1 lands the schema + models + schemas + an empty data-access
file. The wiring lands in:

* Step 2 — service + condition evaluator + recipient resolvers
* Step 3 — router + permissions
* Step 4 — Celery dispatcher
* Step 5 — first publisher (``user.signed_up`` from auth)
* Step 6 — ``lead.created`` from every lead-capture source
* Steps 7-9 — Settings → Automations UI
* Steps 10-14 — appointment / quote / invoice / time-based
  publishers + frequency cap + deliverability polish

See ``tasks/automation-engine/README.md`` for the full plan."""

# Step 4 — wildcard bus subscriber. Side-effect import at module
# load time so every FastAPI worker registers the dispatcher once
# without main.py needing a dedicated wiring line. The conversations
# adapters follow the same pattern.
# tasks/automation-conditions/ Step 2 — side-effect import so every
# built-in enum resolver registers with the module-level registry
# before the app serves its first ``/field-values`` request. Kept
# below the dispatcher import for load-order clarity (both are
# side-effect imports; neither has actual runtime deps on the other).
from src.app.core.automation import enum_resolvers  # noqa: F401 — import side-effect
from src.app.core.automation.dispatcher import register_bus_subscriber

register_bus_subscriber()
