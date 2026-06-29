"""Process-local pub/sub primitives for CRM domain events.

The bus is one module-level dict — ``event_type → list[handler]``.
Subscribers register at module-import time during the FastAPI
lifespan startup (the conversations adapters use the same pattern).
The publisher awaits each registered handler in turn; failures are
logged + swallowed so one bad subscriber doesn't poison the rest.

Step 1 of ``tasks/automation-engine/`` lands the primitives. No
domain events publish yet; no automation handlers are subscribed
yet. Step 4 wires the automation dispatcher as a subscriber; Steps
5 / 6 / 10 / 11 / 12 wire the actual publish() calls from the
origin modules (``user.signed_up`` from auth, ``lead.created``
from every lead-capture source, etc.).

Multi-worker note: the bus is process-local — each uvicorn worker +
each Celery worker has its own dict. For v1 the actual handler
work that needs cross-process consistency runs through the Celery
task queue (the dispatcher Step 4 ships); the bus only routes from
"publish call" to "queue a Celery job". When a future step needs
true cross-worker fan-out (e.g. WebSocket push from any worker),
swap this module's dict for a Redis-backed pub/sub without changing
the call surface.

Event-type taxonomy (string constants — modules importing this
should pull from this list, not hardcode):

Auth + onboarding
    ``user.signed_up`` — a fresh Owner finishes registration
    ``user.invited`` — operator invites a new team member
    ``user.invitation_accepted`` — invited user finishes signup
    ``user.first_login`` — first successful login after signup
    ``user.role_changed`` — membership role changes (Owner-only)

Leads + contacts
    ``lead.created`` — fired by EVERY lead-capture source
                       (form widget, Google/Meta Ads webhook, CSV
                       import, manual entry, walk-in, WhatsApp
                       inbound new-contact, API direct)
    ``lead.status_changed`` — status transition
    ``lead.score_threshold`` — score crosses a configured threshold
    ``lead.assigned`` — owner assignment changes
    ``lead.converted`` — lead → contact promotion
    ``lead.stale_7d`` / ``lead.stale_30d`` / ``lead.stale_90d``
    ``contact.created``
    ``contact.birthday`` — daily sweep finds a contact's birthday
    ``contact.anniversary``
    ``contact.opt_in_changed``

Appointments + walk-ins
    ``appointment.booked``
    ``appointment.reminder_24h`` / ``appointment.reminder_1h``
    ``appointment.completed`` / ``appointment.missed``
    ``walk_in.registered``

Sales
    ``quote.sent`` / ``quote.viewed`` / ``quote.accepted`` /
    ``quote.rejected`` / ``quote.expired``
    ``invoice.sent`` / ``invoice.paid``
    ``invoice.overdue_7d`` / ``invoice.overdue_14d`` /
    ``invoice.overdue_30d``

Communications
    ``email.opened`` / ``email.clicked`` / ``email.replied``
    ``whatsapp.message_received`` / ``whatsapp.template_replied``

Time-based (emitted by the daily sweep)
    ``time.daily_tick`` — once a day at org-local midnight
"""
from __future__ import annotations

import inspect
import logging
import uuid
from typing import Any, Awaitable, Callable, Union


logger = logging.getLogger(__name__)


#: Handler signature — coroutine fn called with the published
#: payload (already enriched with ``org_id``). Sync callables are
#: also accepted to keep test fixtures simple; their return value
#: is discarded.
EventHandler = Callable[[dict[str, Any]], Union[None, Awaitable[None]]]


# Process-local registry. Keyed by exact event-type string match;
# wildcard patterns are NOT supported (would invite surprise fan-out)
# beyond the explicit `subscribe_all` shape below.
_subscribers: dict[str, list[EventHandler]] = {}

# Step 4 — wildcard subscribers. The automation engine's dispatcher
# registers here so a single coroutine fans every event into the
# match-triggers flow without needing 30+ explicit subscribe() calls.
# Keep this list small (one or two entries at most); per-event
# subscribers stay the dominant pattern for per-type handlers.
_wildcard_subscribers: list[EventHandler] = []


def subscribe(event_type: str, handler: EventHandler) -> None:
    """Register ``handler`` to receive every ``publish(event_type, …)``
    fire-and-forget event going forward. Safe to call before any
    publishers exist — the handler simply never fires until something
    publishes.

    Registration is idempotent on ``(event_type, handler)`` — calling
    twice doesn't double-fire the handler."""
    bucket = _subscribers.setdefault(event_type, [])
    if handler in bucket:
        return
    bucket.append(handler)


def unsubscribe(event_type: str, handler: EventHandler) -> None:
    """Remove a handler. Mostly a test helper — production
    subscribers register at app-start + stay registered for the
    process lifetime."""
    bucket = _subscribers.get(event_type)
    if not bucket:
        return
    try:
        bucket.remove(handler)
    except ValueError:
        return


def subscribe_all(handler: EventHandler) -> None:
    """Register ``handler`` to fire on **every** published event,
    regardless of event_type. Used by the automation dispatcher to
    fan all events into the match-triggers flow without enumerating
    every catalog entry. Idempotent on the same handler reference."""
    if handler in _wildcard_subscribers:
        return
    _wildcard_subscribers.append(handler)


def unsubscribe_all(handler: EventHandler) -> None:
    """Remove a wildcard handler. Test helper + symmetry with the
    per-event ``unsubscribe`` helper."""
    try:
        _wildcard_subscribers.remove(handler)
    except ValueError:
        return


async def publish(
    event_type: str,
    payload: dict[str, Any],
    *,
    org_id: uuid.UUID,
    event_id: str | None = None,
) -> None:
    """Fire ``event_type`` with ``payload`` to every registered
    handler. The published envelope is the caller's payload merged
    with ``{"org_id": org_id, "event_type": event_type, "event_id":
    event_id}`` so handlers always see who fired what + can dedupe
    on replays.

    ``event_id`` is the publisher-supplied idempotency key. When
    omitted, a fresh UUID is generated — idempotency then becomes
    per-fire (no dedupe across replays). Origin modules SHOULD pass
    a stable id (typically the originating row's PK) so the
    automation dispatcher's ``(trigger_id, event_id)`` unique index
    absorbs at-least-once delivery.

    Per-event-type subscribers fire first (deterministic registry
    order), then wildcard subscribers. Each handler is awaited in
    turn; failures are logged and swallowed so one bad subscriber
    doesn't poison the rest + the publisher's transaction completes
    regardless.
    """
    if event_id is None:
        event_id = str(uuid.uuid4())
    envelope: dict[str, Any] = {
        **payload,
        "org_id": org_id,
        "event_type": event_type,
        "event_id": event_id,
    }
    typed = list(_subscribers.get(event_type, ()))
    wildcard = list(_wildcard_subscribers)
    if not typed and not wildcard:
        logger.debug(
            "events.publish no_subscribers event_type=%s org_id=%s",
            event_type,
            org_id,
        )
        return
    for handler in (*typed, *wildcard):
        try:
            result = handler(envelope)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception(
                "events.handler_failed event_type=%s handler=%s",
                event_type,
                getattr(handler, "__qualname__", repr(handler)),
            )


def _clear_subscribers_for_tests() -> None:
    """Test helper — wipes both registries between cases so
    subscribers from one test don't bleed into the next. NOT
    exported via ``__all__``; intentionally underscore-prefixed."""
    _subscribers.clear()
    _wildcard_subscribers.clear()


__all__ = [
    "EventHandler",
    "publish",
    "subscribe",
    "subscribe_all",
    "unsubscribe",
    "unsubscribe_all",
]
