"""Domain event bus — pub/sub primitives shared by automation + workflows.

Origin modules (auth, leads, appointments, quotes, invoices, …)
``publish()`` events; consumer modules (automation engine today,
workflows engine in the future) ``subscribe()`` to event types.

The bus is intentionally in-process for v1. Process-local fan-out
mirrors the channel-registry pattern used by ``core/conversations/``
— it's enough for the single-tenant, single-FastAPI-app deploy
shape while keeping the API surface small. A Redis-backed fan-out
that lets a separate worker pool consume events is a follow-up
once we need it.

Two concepts live here:

* ``bus.subscribe(event_type, handler)`` — register a coroutine
  handler for an event type. Called at module-import time during
  the FastAPI lifespan startup (mirrors the conversations channel
  registry's side-effect import pattern).
* ``bus.publish(event_type, payload, *, org_id)`` — fire an event.
  Each matching handler is awaited in turn; failures are logged
  + swallowed so one bad handler doesn't block the rest.

See :mod:`core.events.bus` for the canonical event-type taxonomy
strings (``user.signed_up``, ``lead.created``, …) — handlers SHOULD
import the constants from there rather than hardcoding strings.
"""

from src.app.core.events.bus import (
    publish,
    subscribe,
    subscribe_all,
    unsubscribe,
    unsubscribe_all,
)

__all__ = [
    "publish",
    "subscribe",
    "subscribe_all",
    "unsubscribe",
    "unsubscribe_all",
]
