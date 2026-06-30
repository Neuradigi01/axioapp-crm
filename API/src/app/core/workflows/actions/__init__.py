"""Action registry — the workflow engine's pluggable action layer.

Mirrors :mod:`core.conversations.registry` — a module-level dict
maps an action-type string (e.g. ``"send.email"``,
``"record.update_contact"``, ``"flow.branch_if"``) to a zero-arg
factory that returns the action's handler. Steps 7-11 populate it
with concrete actions (Send / Record / Routing / Tagging / Flow
control).

Registration is side-effect-driven: each action module's
``__init__`` calls :func:`register_action` at import time, so once
the engine imports the module the action is available. Step 4's
engine resolves the handler per node execution via
:func:`resolve`.

Per-process state (one dict per uvicorn / Celery worker). The
pattern matches the conversations channel registry; a future
config-driven rewrite would slot in here without touching the
engine's call sites.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class ActionNotRegistered(Exception):
    """Raised when the engine encounters an unknown action type."""


#: Factory signature — zero-arg callable returning a handler. The
#: handler shape is fixed by Step 4's engine (``async def execute(
#: session, run, node, config) -> StepResult``); we don't typehint
#: it here so Steps 7-11 can register lightweight callables for
#: tests + heavier service-backed handlers in production.
ActionFactory = Callable[[], Any]


_factories: dict[str, ActionFactory] = {}


def register_action(
    action_type: str,
    factory: ActionFactory,
) -> None:
    """Register a handler factory for ``action_type``. Idempotent —
    re-registering the same type silently overwrites (Steps 7-11's
    test fixtures rely on this for hot-swapping)."""
    _factories[action_type] = factory


def unregister_action(action_type: str) -> None:
    """Test helper — drop a previously registered factory. The
    engine never calls this in production."""
    _factories.pop(action_type, None)


def resolve(action_type: str) -> Any:
    """Resolve + construct the handler for ``action_type``. Raises
    :class:`ActionNotRegistered` when the type isn't on the
    registry — the engine catches this + records the step run as
    ``errored`` with ``error='unknown_action'``."""
    factory = _factories.get(action_type)
    if factory is None:
        raise ActionNotRegistered(f"no handler registered for action type '{action_type}'")
    return factory()


def is_registered(action_type: str) -> bool:
    """Quick test-helper / introspection check — does the registry
    know this action type?"""
    return action_type in _factories


def list_registered() -> list[str]:
    """Stable-ordered list of registered action types — useful for
    the Step-15 node-editor drawer that surfaces the operator's
    pickable actions."""
    return sorted(_factories.keys())


def _clear_registry_for_tests() -> None:
    """Wipe the registry between test cases so registrations don't
    bleed across runs. NOT exported via ``__all__``. Built-ins are
    NOT auto-restored — tests that need them call
    :func:`_register_builtins` explicitly so the existing Step-1
    test_action_registry.py cases (which count exactly the keys
    they registered) still pass."""
    _factories.clear()


# --- Built-in handlers ----------------------------------------------------


async def _trigger_handler(session, *, run, step_run, node, context):
    """No-op pass-through for trigger nodes. The Step-5 trigger
    subscribers do the actual event-payload extraction during
    ``start_run``; by the time the engine processes the trigger
    node here, it just needs a row in ``tbl_workflow_step_runs``
    + an immediate advance to the next node."""
    from src.app.core.workflows.engine import ActionResult

    return ActionResult()


async def _flow_wait_handler(session, *, run, step_run, node, context):
    """No-op pass-through. The engine's ``_advance`` recognises wait
    nodes by type AFTER the handler returns + parks the run with
    ``next_step_at`` set. Step 11 will refine this to honour
    ``flow.wait_for_event`` semantics + cancel-on-resume conditions;
    for v1 the engine handles the parking inline."""
    from src.app.core.workflows.engine import ActionResult

    return ActionResult()


async def _flow_end_handler(session, *, run, step_run, node, context):
    """No-op terminator. The advance step's "no outbound edges"
    branch turns this into the ``completed`` (or ``goal_reached``)
    run outcome."""
    from src.app.core.workflows.engine import ActionResult

    return ActionResult()


def _register_builtins() -> None:
    """Register the engine's built-in handlers. Called at module
    import + after every ``_clear_registry_for_tests`` so the
    trigger / flow handlers are always available."""
    _factories["trigger"] = lambda: _trigger_handler
    _factories["flow.wait"] = lambda: _flow_wait_handler
    _factories["flow.wait_for_event"] = lambda: _flow_wait_handler
    _factories["flow.end"] = lambda: _flow_end_handler


_register_builtins()


__all__ = [
    "ActionFactory",
    "ActionNotRegistered",
    "is_registered",
    "list_registered",
    "register_action",
    "resolve",
    "unregister_action",
]
