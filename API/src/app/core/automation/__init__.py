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

See ``tasks/automation-engine/README.md`` for the full plan.

Public registration API for packs
---------------------------------

Packs extending the automation catalog import from this namespace
and never touch the underscored internals (``_CATALOG`` /
``_REGISTRY`` / ``_register`` / etc.):

* :func:`register_event` — add a :class:`~core.automation.event_catalog.CatalogEntry`
  (event type + label + description + sample_payload + condition_fields).
* :func:`register_field_resolver` — add an enum resolver by key
  (with ``wildcard=True`` for prefix-matched keys like
  ``fp_warehouses``).

The module-registry walker (:func:`core.module_registry.discover_modules`)
imports each pack's ``event_catalog.py`` at boot inside a
pack-scoped ContextVar so registrations auto-tag with the pack slug
without the pack file needing to hardcode it — the same slug that
appears on ``org.template_id`` for orgs that installed the pack.
The ``/event-types`` + ``/field-values`` endpoints then filter by
that slug so an org only sees fields from packs it has installed."""

# Step 4 — wildcard bus subscriber. Side-effect import at module
# load time so every FastAPI worker registers the dispatcher once
# without main.py needing a dedicated wiring line. The conversations
# adapters follow the same pattern.
# tasks/automation-conditions/ Step 2 — side-effect import so every
# built-in enum resolver registers with the module-level registry
# before the app serves its first ``/field-values`` request. Kept
# below the dispatcher import for load-order clarity (both are
# side-effect imports; neither has actual runtime deps on the other).
from collections.abc import Callable

from src.app.core.automation import enum_resolvers  # noqa: F401 — import side-effect
from src.app.core.automation.dispatcher import register_bus_subscriber
from src.app.core.automation.enum_resolvers import EnumOption, EnumResolver
from src.app.core.automation.event_catalog import CatalogEntry
from src.app.core.automation.field_specs import FieldSpec, FieldType


def register_event(entry: CatalogEntry) -> None:
    """Public registration API for packs. Adds ``entry`` to the
    discovery catalog. When called from a pack's ``event_catalog.py``
    (imported by the module-registry walker), the entry's
    ``pack_id`` auto-populates from the pack-import ContextVar.

    Raises :class:`ValueError` when a declared ``FieldSpec.path``
    doesn't resolve into the entry's ``sample_payload`` (drift
    guard). Idempotent for re-registration of the same event type;
    the last registration wins so a pack can override its own
    entry across reloads.
    """
    from src.app.core.automation.event_catalog import _register

    _register(entry)


def register_field_resolver(
    key: str,
    fn: Callable,
    *,
    wildcard: bool = False,
) -> None:
    """Public registration API for packs. Adds ``fn`` to the enum
    resolver registry under ``key``. Same auto-tagging as
    :func:`register_event` — pack-import calls stamp the resolver
    with the pack's slug so ``/field-values`` filters correctly.

    Raises ``RuntimeError`` on same-key + different-callable
    collisions (see :func:`enum_resolvers.register_resolver`).
    Wildcard keys must end in ``*``.
    """
    enum_resolvers.register_resolver(key, fn, wildcard=wildcard)


register_bus_subscriber()


__all__ = [
    "CatalogEntry",
    "EnumOption",
    "EnumResolver",
    "FieldSpec",
    "FieldType",
    "register_event",
    "register_field_resolver",
]
